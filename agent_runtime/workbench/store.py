from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import replace
from pathlib import Path

from ..atomic_io import atomic_write_json
from .models import ResourceScope
from .recovery import quarantine_path, should_quarantine_error
from .workflows import WORKFLOW_ID_PATTERN, WorkflowDefinition


LOGGER = logging.getLogger(__name__)


_LEGACY_TOOL_FACADES: dict[str, tuple[str, str]] = {
    "git_status": ("git_inspect", "status"),
    "git_diff": ("git_inspect", "diff"),
    "git_log": ("git_inspect", "log"),
    "git_show": ("git_inspect", "show"),
    "git_blame": ("git_inspect", "blame"),
    "write_stdin": ("process_control", "write"),
    "kill_command": ("process_control", "kill"),
    "read_output": ("process_control", "read_output"),
    "skill_list": ("skill_manage", "list"),
    "skill_get": ("skill_manage", "get"),
    "skill_validate": ("skill_manage", "validate"),
    "skill_save": ("skill_manage", "save"),
    "skill_delete": ("skill_manage", "delete"),
    "mcp_connection_list": ("mcp_connection_manage", "list"),
    "mcp_connection_get": ("mcp_connection_manage", "get"),
    "mcp_connection_validate": ("mcp_connection_manage", "validate"),
    "mcp_connection_save": ("mcp_connection_manage", "save"),
    "mcp_connection_delete": ("mcp_connection_manage", "delete"),
    "mcp_connection_test": ("mcp_connection_manage", "test"),
    "mcp_connection_discover_tools": ("mcp_connection_manage", "discover"),
    "mcp_connection_call_tool": ("mcp_connection_manage", "call_tool"),
    "workflow_list": ("workflow_manage", "list"),
    "workflow_get": ("workflow_manage", "get"),
    "workflow_validate": ("workflow_manage", "validate"),
    "workflow_save": ("workflow_manage", "save"),
    "workflow_delete": ("workflow_manage", "delete"),
    "workflow_export": ("workflow_manage", "export"),
    "workflow_import": ("workflow_manage", "import"),
    "workflow_run_list": ("workflow_run", "list"),
    "workflow_start": ("workflow_run", "start"),
    "workflow_status": ("workflow_run", "status"),
    "workflow_continue": ("workflow_run", "continue"),
    "workflow_retry": ("workflow_run", "retry"),
    "workflow_cancel": ("workflow_run", "cancel"),
}

_REMOVED_TOOL_NAMES = frozenset({
    *_LEGACY_TOOL_FACADES,
    "browser_manage",
    "workflow_authoring_context",
})


class WorkflowVersionConflictError(RuntimeError):
    def __init__(self, workflow_id: str, *, expected: int, actual: int) -> None:
        self.workflow_id = workflow_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Workflow version conflict: {workflow_id} expected v{expected}, current workspace version is v{actual}"
        )


class WorkflowStore:
    """Workspace-scoped persistent Workflow definitions."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.directory = self.workspace / ".micromatrix-workbench" / "workflows"

    def _path(self, workflow_id: str) -> Path:
        value = workflow_id.strip()
        if not WORKFLOW_ID_PATTERN.fullmatch(value):
            raise ValueError(f"invalid workflow id: {workflow_id!r}")
        return self.directory / f"{value}.json"

    @staticmethod
    def _migrate_tool_node(node: dict[str, object]) -> tuple[bool, str]:
        if str(node.get("type") or "") != "tool":
            return False, ""
        config = node.get("config")
        if not isinstance(config, dict) or str(config.get("provider") or "system") != "system":
            return False, ""
        tool_name = str(config.get("tool_name") or "")
        arguments = config.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
            config["arguments"] = arguments
        if tool_name == "browser_manage":
            action = str(arguments.get("action") or "").strip().lower()
            if action not in {"open", "navigate", "snapshot", "click", "fill", "press", "screenshot", "status", "close"}:
                return False, f"browser_manage action 无法迁移: {action or '<missing>'}"
            config["tool_name"] = f"browser_{action}"
            arguments.pop("action", None)
            if action == "screenshot" and "path" not in arguments:
                # The old facade always persisted screenshots; keep that explicit
                # behavior in migrated workflows without retaining runtime fallback.
                arguments["path"] = "browser-screenshot.png"
            return True, ""
        facade = _LEGACY_TOOL_FACADES.get(tool_name)
        if facade is not None:
            target, action = facade
            config["tool_name"] = target
            arguments["action"] = action
            return True, ""
        if tool_name in _REMOVED_TOOL_NAMES:
            return False, f"旧工具 {tool_name} 没有安全的一次性迁移目标"
        return False, ""

    def migrate_legacy_tool_references(self) -> dict[str, object]:
        """One-time, backup-first migration of persisted Workflow tool references.

        This runs before WorkflowRegistry is built. It is intentionally not a
        call-time alias layer: after migration only the public contract remains.
        """
        report_root = self.workspace / ".micromatrix-workbench" / "migrations" / "browser-host-contract-reset"
        scanned = 0
        migrated: list[dict[str, object]] = []
        unsupported: list[dict[str, str]] = []
        pending: list[tuple[Path, dict[str, object], list[str]]] = []
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.json")):
                scanned += 1
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    unsupported.append({"path": str(path), "reason": f"Workflow JSON 无法读取: {exc}"})
                    continue
                if not isinstance(raw, dict):
                    unsupported.append({"path": str(path), "reason": "Workflow JSON 不是 object"})
                    continue
                nodes = raw.get("nodes")
                if not isinstance(nodes, list):
                    continue
                changed_tools: list[str] = []
                file_unsupported: list[str] = []
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    config = node.get("config")
                    before = str(config.get("tool_name") or "") if isinstance(config, dict) else ""
                    changed, reason = self._migrate_tool_node(node)
                    if reason:
                        file_unsupported.append(reason)
                    elif changed:
                        after_config = node.get("config")
                        after = str(after_config.get("tool_name") or "") if isinstance(after_config, dict) else ""
                        changed_tools.append(f"{before}->{after}")
                if file_unsupported:
                    unsupported.extend({"path": str(path), "reason": reason} for reason in file_unsupported)
                    continue
                if changed_tools:
                    if isinstance(raw.get("version"), int):
                        raw["version"] = int(raw["version"]) + 1
                    try:
                        WorkflowDefinition.from_mapping(
                            raw,
                            scope=ResourceScope.WORKSPACE,
                            source=f"workspace:{path}",
                        )
                    except (TypeError, ValueError) as exc:
                        unsupported.append({"path": str(path), "reason": f"迁移后 Workflow 无效: {exc}"})
                        continue
                    pending.append((path, raw, changed_tools))

        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if pending:
            backup_root = report_root / "backups" / timestamp
            backup_root.mkdir(parents=True, exist_ok=False)
            for path, raw, changed_tools in pending:
                backup = backup_root / path.name
                shutil.copy2(path, backup)
                atomic_write_json(path, raw)
                migrated.append({
                    "path": str(path),
                    "backup": str(backup),
                    "changes": changed_tools,
                })
        report = {
            "contract_version": 2,
            "scanned": scanned,
            "migrated": migrated,
            "unsupported": unsupported,
            "generated_at": timestamp,
        }
        if migrated or unsupported:
            report_root.mkdir(parents=True, exist_ok=True)
            atomic_write_json(report_root / "report.json", report)
        return report

    def list(self) -> tuple[WorkflowDefinition, ...]:
        if not self.directory.is_dir():
            return ()
        definitions: list[WorkflowDefinition] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                definitions.append(self._read(path))
            except RuntimeError as exc:
                LOGGER.warning("Skipping invalid Workflow %s: %s", path, exc)
                if should_quarantine_error(exc):
                    quarantine_path(path, reason=str(exc))
        return tuple(sorted(definitions, key=lambda item: item.id))

    def get(self, workflow_id: str) -> WorkflowDefinition | None:
        path = self._path(workflow_id)
        if not path.is_file():
            return None
        return self._read(path)

    def save(
        self,
        workflow: WorkflowDefinition,
        *,
        expected_version: int | None = None,
    ) -> WorkflowDefinition:
        current = self.get(workflow.id)
        current_version = current.version if current is not None else 0
        if expected_version is not None and int(expected_version) != current_version:
            raise WorkflowVersionConflictError(
                workflow.id,
                expected=int(expected_version),
                actual=current_version,
            )
        version = current_version + 1
        path = self._path(workflow.id)
        persisted = replace(
            workflow,
            version=version,
            scope=ResourceScope.WORKSPACE,
            source=f"workspace:{path}",
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, persisted.to_dict())
        return persisted

    def delete(self, workflow_id: str) -> bool:
        path = self._path(workflow_id)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def _read(self, path: Path) -> WorkflowDefinition:
        if path.is_symlink():
            raise RuntimeError(f"Workflow 文件不允许是符号链接: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Workflow 文件损坏: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Workflow 文件必须是 JSON object: {path}")
        try:
            return WorkflowDefinition.from_mapping(
                payload,
                scope=ResourceScope.WORKSPACE,
                source=f"workspace:{path}",
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Workflow 定义无效: {path}: {exc}") from exc
