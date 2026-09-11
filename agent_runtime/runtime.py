"""Business runtime for the project-owned MicroMatrix Workbench tools."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from threading import RLock
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .core.constants import SERVER_NAME, SERVER_TITLE
from .core.dispatcher import ToolDispatcher
from .errors import RpcError, ToolError
from .processes import CommandManager
from .project_context import ProjectContext, load_project_context
from .local_permission_broker import LocalWorkflowApprovalBrokerClient
from .oauth_service import OAuthService
from .protocol import ACTIVE_REQUEST_CONTEXT, RequestContext, current_request_context
from .permissions.capabilities import (
    ELICITABLE_PERMISSIONS,
    PERMISSION_MODES,
    permission_profile,
)
from .permissions.context import ACTIVE_PERMISSIONS
from .permissions.policy import PermissionPolicy
from .permissions.session import PermissionSession
from .permissions.state import arguments_digest
from .results import make_tool_result
from .sandbox import build_sandbox_profile, create_process_sandbox
from .tools import build_tool_registry
from .tools.browser.handlers import BrowserHandlers
from .tools.desktop.handlers import DesktopHandlers
from .tools.filesystem.handlers import FilesystemHandlers
from .tools.git.handlers import GitHandlers
from .tools.process.handlers import ProcessHandlers
from .tools.system.handlers import SystemHandlers
from .tools.toolchains.handlers import ToolchainHandlers
from .tools.workbench.handlers import WorkbenchHandlers
from .toolchains import ToolchainResolver
from .toolchains.registration import (normalize_registrations, fingerprint,
                                      require_confinement, write_launchers)
from .toolchains.paths import system_read_roots
from .workspace import Workspace
from .workbench.capability_assets import CapabilityAssetService
from .workbench.engine import WorkflowEngine
from .workbench.mcp_connection_service import MCPConnectionService
from .workbench.registry import build_workflow_registry
from .workbench.runs import WorkflowRunManager
from .workbench.store import WorkflowStore


LOGGER = logging.getLogger(__name__)


class Runtime(
    FilesystemHandlers,
    BrowserHandlers,
    DesktopHandlers,
    ProcessHandlers,
    GitHandlers,
    SystemHandlers,
    ToolchainHandlers,
    WorkbenchHandlers,
):
    def __init__(
        self,
        workspace: Path,
        *,
        permission_mode: str = "safe",
        allow_network: bool = False,
        auth_token: str | None = None,
        oauth_service: OAuthService | None = None,
        enable_view_image: bool = True,
        fake_readonly_annotations: bool = False,
        project_context: ProjectContext | None = None,
        permission_broker: Any | None = None,
        permission_broker_from_env: bool = True,
        global_asset_root: Path | None = None,
        toolchains: Sequence[dict[str, Any]] = (),
    ) -> None:
        if permission_mode not in PERMISSION_MODES:
            raise ValueError(f"unknown permission mode: {permission_mode}")
        if fake_readonly_annotations and permission_mode != "dangerous":
            raise ValueError("fake_readonly_annotations requires dangerous permission mode")
        self.toolchain_registrations = normalize_registrations(toolchains)
        self._verify_toolchain_files()
        self.workspace = Workspace(workspace)
        self.tool_registry = build_tool_registry()
        self.mcp_connections = MCPConnectionService(global_root=global_asset_root)
        self.capability_assets = CapabilityAssetService(global_root=global_asset_root)
        self.skill_registry = self.capability_assets.skill_registry
        self.workflow_store = WorkflowStore(self.workspace.root)
        workflow_migration = self.workflow_store.migrate_legacy_tool_references()
        if workflow_migration.get("unsupported"):
            report = (
                self.workspace.root
                / ".micromatrix-workbench"
                / "migrations"
                / "browser-host-contract-reset"
                / "report.json"
            )
            raise RuntimeError(
                "检测到无法自动迁移的旧 Workflow 工具引用；未启用运行时兼容入口。"
                f"请检查迁移报告: {report}"
            )
        self.workflow_registry = build_workflow_registry(
            store=self.workflow_store,
        )
        self.permission_mode = permission_mode
        self.permission_profile = permission_profile(permission_mode)
        self.permission_policy = PermissionPolicy(self.permission_profile)
        self.allow_network = allow_network or permission_mode in {"trusted", "dangerous"}
        self.auth_token = auth_token
        self.oauth_service = oauth_service
        self.enable_view_image = enable_view_image
        self.fake_readonly_annotations = fake_readonly_annotations
        self.project_context = project_context or load_project_context(self.workspace.root)
        self.commands = CommandManager(self.workspace.root)
        self.permission_session = PermissionSession(
            self.workspace.root,
            broker_client=permission_broker,
            load_broker_from_env=permission_broker_from_env,
        )
        self._toolchain_registration_lock = RLock()
        self._toolchain_consent_denied: set[str] = set()
        self._toolchain_state_dir = self.commands.runtime_dir / "toolchain-state"
        self._toolchain_state_dir.mkdir(mode=0o700)
        self.safe_exec_path = ToolchainResolver.default_search_path(self.workspace.root)
        registered_roots = list(dict.fromkeys(
            Path(root) for item in self.toolchain_registrations for root in item["read_roots"]
        ))
        self.registered_bin_dir = write_launchers(self.toolchain_registrations, self.commands.runtime_dir)
        self.safe_exec_path = list(dict.fromkeys([
            *([str(self.registered_bin_dir)] if self.registered_bin_dir else []),
            *(str(Path(item["executable"]).parent) for item in self.toolchain_registrations),
            *self.safe_exec_path,
        ]))
        self.toolchain_read_roots: list[Path] = registered_roots
        if permission_mode != "dangerous":
            self.workspace.readonly_roots = tuple(registered_roots)
        sandbox_readable_roots = [*registered_roots, *self._platform_read_roots()]
        sandbox_writable_roots = [
            self.commands.runtime_dir,
            self.commands.home_dir,
            self.commands.tmp_dir,
            self.commands.cache_dir,
        ]
        sandbox_protected_paths = [
            path
            for path in (self.workspace.root / ".git",)
            if path.exists()
        ]
        sandbox_protected_paths.append(self._toolchain_state_dir)
        sandbox_protected_paths.extend(registered_roots)
        if self.registered_bin_dir:
            sandbox_protected_paths.append(self.registered_bin_dir)
        # Build the baseline sandbox before discovery. Tool lookup and version
        # probes must observe the same filesystem/PATH restrictions as commands.
        self.process_sandbox = create_process_sandbox(
            mode=self.permission_mode,
            workspace=self.workspace.root,
            runtime_dir=Path(tempfile.mkdtemp(prefix="initial-", dir=self._toolchain_state_dir)),
            readable_roots=sandbox_readable_roots,
            writable_roots=sandbox_writable_roots,
            protected_paths=sandbox_protected_paths,
            network=self.allow_network,
        )
        self.toolchains = ToolchainResolver(
            self.workspace.root,
            safe_path=self.safe_exec_path,
            probe_runner=self._run_toolchain_probe,
            unrestricted=self.permission_mode == "dangerous",
            registered_programs={item["program"]: item["executable"]
                                 for item in self.toolchain_registrations},
        )
        self._toolchain_snapshot = self.toolchains.discover(probe_versions=False)
        self.safe_exec_path = list(dict.fromkeys([
            *([str(self.registered_bin_dir)] if self.registered_bin_dir else []),
            *(str(item) for item in self._toolchain_snapshot.get("safe_path", [])),
        ]))
        # Successful version probes are evidence, not authorization. Inferred
        # installation parents must never widen the already-approved read roots.
        self.sandbox_profile = build_sandbox_profile(
            mode=self.permission_mode,
            workspace=self.workspace.root,
            runtime_paths=sandbox_writable_roots,
            toolchain_paths=[str(path) for path in self.toolchain_read_roots],
            protected_paths=sandbox_protected_paths,
            network=self.allow_network,
            backend=self.process_sandbox.state,
        )
        if self.sandbox_profile.to_dict()["isolation_level"] != "full":
            LOGGER.warning("执行隔离状态=%s: %s (%s)",
                           self.sandbox_profile.to_dict()["isolation_level"],
                           self.sandbox_profile.to_dict()["security_warning"],
                           self.sandbox_profile.backend_reason)
        enabled_features = frozenset({"view_image"}) if enable_view_image else frozenset()
        self.tool_dispatcher = ToolDispatcher(
            self.tool_registry,
            self,
            enabled_features=enabled_features,
        )
        self._tools = self.tool_dispatcher.definitions
        self.workflow_engine = WorkflowEngine(self)
        self.workflow_runs = WorkflowRunManager(
            self.workspace.root,
            engine=self.workflow_engine,
            registry=self.workflow_registry,
            approval_broker=LocalWorkflowApprovalBrokerClient.from_env(),
        )

    def _install_registered_toolchain(self, record: dict[str, Any]) -> None:
        """Hot-add approved roots; old commands keep their immutable policy generation."""
        records = normalize_registrations(tuple(
            r for r in self.toolchain_registrations if r["program"] != record["program"]
        ) + (record,))
        roots = list(dict.fromkeys(Path(p) for r in records for p in r["read_roots"]))
        generation = Path(tempfile.mkdtemp(prefix="generation-", dir=self._toolchain_state_dir))
        bin_dir = write_launchers(records, generation)
        writable = [self.commands.runtime_dir, self.commands.home_dir,
                    self.commands.tmp_dir, self.commands.cache_dir]
        protected = [self.workspace.root / ".git", self._toolchain_state_dir, *roots]
        if self.registered_bin_dir:
            protected.append(self.registered_bin_dir)
        readable = list(dict.fromkeys([*roots, *self.toolchain_read_roots, *self._platform_read_roots()]))
        safe_path = [str(bin_dir), *[p for p in self.safe_exec_path if p != str(self.registered_bin_dir)]]
        for r in records:
            if (fingerprint(r["executable"], r["read_roots"]) != r["fingerprint"]
                or (r["runtime_target"] and fingerprint(r["runtime_target"], r["read_roots"]) != r["runtime_fingerprint"])):
                raise ToolError("TOOLCHAIN_REGISTRATION_STALE", "工具注册后文件已变化，请重新确认。", "process", False)
        task_generation = Path(tempfile.mkdtemp(prefix="task-", dir=self._toolchain_state_dir))
        backend = create_process_sandbox(
            mode=self.permission_mode, workspace=self.workspace.root, runtime_dir=task_generation,
            readable_roots=readable, writable_roots=writable,
            protected_paths=protected, network=self.allow_network,
        )
        if self.permission_mode != "dangerous":
            require_confinement(backend)
            self.workspace.readonly_roots = tuple(roots)
        self.process_sandbox = backend
        self.safe_exec_path = safe_path
        self.registered_bin_dir = bin_dir
        self.toolchain_read_roots = list(dict.fromkeys([*roots, *self.toolchain_read_roots]))
        self.toolchain_registrations = records
        self.toolchains = ToolchainResolver(
            self.workspace.root, safe_path=safe_path, probe_runner=self._run_toolchain_probe,
            unrestricted=self.permission_mode == "dangerous",
            registered_programs={r["program"]: r["executable"] for r in records},
        )
        self._toolchain_snapshot = self.toolchains.discover(probe_versions=False)
        self.sandbox_profile = build_sandbox_profile(
            mode=self.permission_mode, workspace=self.workspace.root, runtime_paths=writable,
            toolchain_paths=[str(p) for p in self.toolchain_read_roots],
            protected_paths=protected, network=self.allow_network, backend=backend.state,
        )

    @property
    def local_permission_broker(self) -> Any | None:
        """Compatibility facade for tests/desktop integrations.

        The broker is owned by PermissionSession; callers that historically
        injected runtime.local_permission_broker keep working unchanged.
        """

        return self.permission_session.broker_client

    @local_permission_broker.setter
    def local_permission_broker(self, value: Any | None) -> None:
        self.permission_session.broker_client = value

    def close(self) -> None:
        self.commands.close()

    def _verify_toolchain_files(self) -> None:
        for item in self.toolchain_registrations:
            try:
                actual = fingerprint(item["executable"], item["read_roots"])
                if actual != item["fingerprint"]:
                    raise ValueError("executable or target changed")
                if item["runtime_target"] and fingerprint(item["runtime_target"], item["read_roots"]) != item["runtime_fingerprint"]:
                    raise ValueError("runtime executable changed")
            except (OSError, ValueError) as exc:
                raise ToolError("TOOLCHAIN_REGISTRATION_STALE",
                                f"工具链 {item['program']} 路径或文件发生变化，请在桌面重新确认并注册。",
                                "process", False) from exc

    def _verify_registered_toolchains(self) -> None:
        """Compatibility hook: registrations are verified by immutable file identity only."""
        self._verify_toolchain_files()

    @staticmethod
    def _platform_read_roots() -> list[Path]:
        return system_read_roots()

    def _run_toolchain_probe(
        self,
        argv: list[str],
        env: Mapping[str, str],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        if self.toolchain_registrations:
            registered_env = self._command_env({})
            env = {**registered_env, **dict(env)}
            env["HOME"] = str(Path.home())
        # Discovery observes the already-approved boundary. No per-probe Home/root grants.
        command = self.process_sandbox.wrap(argv, cwd=self.workspace.root)
        return subprocess.run(
            command,
            cwd=str(self.workspace.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            shell=False,
            env=dict(env),
        )

    def server_identity(self) -> dict[str, str]:
        return {"name": SERVER_NAME, "title": SERVER_TITLE, "version": __version__}

    def server_instructions(self) -> str:
        """Return MCP guidance with the latest user-authored Workflow catalog."""
        self._refresh_workspace_workflows()
        return self.project_context.server_instructions(self.workflow_registry.list())

    def auth_enabled(self) -> bool:
        return bool(self.auth_token or self.oauth_service)

    def list_tools(self) -> dict[str, Any]:
        return {
            "tools": [
                definition.mcp_definition(
                    fake_readonly=self.fake_readonly_annotations
                )
                for definition in self._tools
            ]
        }

    def _permission_granted(self, permission: str) -> bool:
        return (
            permission in ACTIVE_PERMISSIONS.get()
            or self.permission_policy.operation_is_auto_granted(permission)
        )

    def _assert_tool_capabilities(self, name: str, capabilities: Any) -> None:
        missing = self.permission_policy.missing_capabilities(capabilities)
        if not missing:
            return
        raise RpcError(
            -32602,
            f"Tool is not available in permission profile: {name}",
            {
                "reason": "capability_denied",
                "missing_capabilities": sorted(
                    capability.value for capability in missing
                ),
            },
        )

    def _effective_permissions(
        self,
        name: str,
        arguments: dict[str, Any],
        context: RequestContext | None,
        round_granted: frozenset[str],
    ) -> frozenset[str]:
        stored = self.permission_session.stored_permissions_for_call(
            name,
            arguments,
            context,
        )
        session = self.permission_session.session_permissions_for_call(context)
        desktop_session = self.permission_session.desktop_session_permissions_for_call(
            name,
            arguments,
            context,
        )
        return frozenset(
            {
                *ACTIVE_PERMISSIONS.get(),
                *round_granted,
                *stored,
                *session,
                *desktop_session,
            }
        )

    @staticmethod
    def _permission_target(arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        target_tool = str(arguments.get("tool_name") or "")
        raw_arguments = arguments.get("arguments")
        target_arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        return target_tool, target_arguments

    def _store_permission_result(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        permission: str,
        context: RequestContext | None,
        scope: str,
        ttl_seconds: int,
        constraint_scope: str | None = None,
        via: str | None = None,
    ) -> dict[str, Any]:
        target_tool, target_arguments = self._permission_target(arguments)
        grant_id, expires_at = self.permission_session.store_grant(
            tool_name=target_tool,
            arguments=target_arguments,
            permission=permission,
            principal=context.principal if context else "anonymous",
            scope=scope,
            ttl_seconds=ttl_seconds,
        )
        constraints = {
            "tool_name": target_tool,
            "arguments_hash": arguments_digest(
                target_tool,
                target_arguments,
            ),
            "permission": permission,
            "scope": constraint_scope or scope,
        }
        if via:
            constraints["via"] = via
        return make_tool_result(
            name,
            {
                "ok": True,
                "status": "granted",
                "grant_id": grant_id,
                "expires_at": expires_at,
                "constraints": constraints,
            },
        )

    def _handle_permission_required(
        self,
        name: str,
        arguments: dict[str, Any],
        exc: ToolError,
        *,
        context: RequestContext | None,
        granted: frozenset[str],
        permission_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        permission = str(exc.details.get("permission") or "")
        if (
            exc.code != "PERMISSION_REQUIRED"
            or not permission
            or permission in granted
        ):
            return None

        local_broker_configured = self.permission_session.broker_client is not None
        status = "unavailable"
        decision = None
        display_arguments = (
            {**arguments, "_trusted_context": permission_context}
            if permission_context
            else arguments
        )
        if local_broker_configured:
            decision = self.permission_session.request_local_permission(
                name=name,
                arguments=arguments,
                display_arguments=display_arguments,
                permission=permission,
                message=exc.message,
                context=context,
            )
            status = str(getattr(decision, "status", "unavailable"))
        session_scope = (
            status == "approved"
            and str(getattr(decision, "scope", "once")) == "session"
        )
        desktop_session_scope = (
            status == "approved"
            and str(getattr(decision, "scope", "once")) == "desktop_session"
            and name == "desktop"
            and bool(str(arguments.get("session_id") or "").strip())
        )
        if status == "approved":
            if session_scope:
                self.permission_session.grant_session_permissions(context)
            if desktop_session_scope:
                self.permission_session.grant_desktop_session_permission(
                    context,
                    str(arguments.get("session_id") or ""),
                    permission,
                )
            if name == "request_permissions":
                scope = "session" if session_scope else str(arguments.get("scope") or "once")
                return self._store_permission_result(
                    name,
                    arguments,
                    permission=permission,
                    context=context,
                    scope=scope,
                    ttl_seconds=(
                        3_600
                        if session_scope
                        else int(arguments.get("ttl_seconds", 300))
                    ),
                    constraint_scope=("session_all" if session_scope else scope),
                    via="desktop_permission_broker",
                )
            retry_permissions = (
                ELICITABLE_PERMISSIONS
                if session_scope
                else frozenset({*granted, permission})
            )
            retry_token = ACTIVE_PERMISSIONS.set(retry_permissions)
            try:
                return self.call_tool(name, arguments, context=context)
            finally:
                ACTIVE_PERMISSIONS.reset(retry_token)

        if status == "denied":
            payload = {
                "ok": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "用户在 MicroMatrix Workbench 桌面端拒绝了本次授权。",
                    "category": "permission",
                    "retryable": False,
                    "details": {"permission": permission},
                },
            }
            return make_tool_result(name, payload)

        if status == "timeout":
            return make_tool_result(
                name,
                {
                    "ok": False,
                    "error": {
                        "code": "PERMISSION_TIMEOUT",
                        "message": "等待 MicroMatrix Workbench 桌面端授权超时。",
                        "category": "permission",
                        "retryable": True,
                        "details": {"permission": permission},
                    },
                },
            )

        input_required = self.permission_session.input_required(
            name=name,
            arguments=arguments,
            display_arguments=display_arguments,
            permission=permission,
            message=exc.message,
            context=context,
            granted=granted,
        )
        if input_required is not None:
            return input_required

        if name == "request_permissions":
            if local_broker_configured:
                code = "PERMISSION_BROKER_UNAVAILABLE"
                message = "Workbench 桌面权限 Broker 当前不可用，且 MCP 客户端未提供可用的 elicitation form。"
            else:
                code = "ELICITATION_UNSUPPORTED"
                message = "当前 Runtime 未连接 Workbench 桌面权限 Broker，且 MCP 客户端未声明可用的 elicitation form capability。"
            payload = {
                "ok": False,
                "status": "unsupported",
                "grant_id": None,
                "expires_at": None,
                "error": {
                    "code": code,
                    "message": message,
                    "category": "permission",
                    "retryable": local_broker_configured,
                    "details": {
                        "permission": permission,
                        "desktop_broker_configured": local_broker_configured,
                        "requested": arguments,
                    },
                },
            }
        else:
            payload = {"ok": False, "error": exc.payload()}
        return make_tool_result(name, payload)

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        if context is None:
            context = current_request_context()
        definition, handler = self.tool_dispatcher.resolve(name, arguments)
        self._assert_tool_capabilities(name, definition.capabilities)
        image: tuple[str, str] | None = None
        permission_context: dict[str, Any] | None = None
        if definition.preflight_handler_name:
            preflight_handler = getattr(self, definition.preflight_handler_name, None)
            if not callable(preflight_handler):
                return make_tool_result(
                    name,
                    {
                        "ok": False,
                        "error": {
                            "code": "TOOL_PREFLIGHT_UNAVAILABLE",
                            "message": f"工具 {name} 缺少预检实现。",
                            "category": "runtime",
                            "retryable": False,
                            "details": {},
                        },
                    },
                )
            preflight_context_token = ACTIVE_REQUEST_CONTEXT.set(context)
            try:
                try:
                    candidate = preflight_handler(arguments)
                    if isinstance(candidate, dict):
                        permission_context = candidate
                except ToolError as exc:
                    return make_tool_result(name, {"ok": False, "error": exc.payload()})
            finally:
                ACTIVE_REQUEST_CONTEXT.reset(preflight_context_token)
        round_granted, denied = self.permission_session.permission_round(
            name,
            arguments,
            context,
        )
        if denied:
            return make_tool_result(
                name,
                {
                    "ok": False,
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": "用户拒绝或取消了本次临时授权。",
                        "category": "permission",
                        "retryable": False,
                        "details": {},
                    },
                },
            )
        granted = self._effective_permissions(
            name,
            arguments,
            context,
            round_granted,
        )
        if name == "request_permissions":
            requested_permission = str(arguments.get("permission") or "")
            if requested_permission in granted:
                session_granted = requested_permission in self.permission_session.session_permissions_for_call(context)
                scope = "session" if session_granted else str(arguments.get("scope") or "once")
                return self._store_permission_result(
                    name,
                    arguments,
                    permission=requested_permission,
                    context=context,
                    scope=scope,
                    ttl_seconds=(3_600 if session_granted else int(arguments.get("ttl_seconds", 300))),
                    constraint_scope=("session_all" if session_granted else scope),
                    via=("existing_session_grant" if session_granted else None),
                )
        required_permissions = definition.required_operation_permissions(arguments)
        for operation_permission in sorted(
            required_permissions,
            key=lambda item: item.value,
        ):
            permission = operation_permission.value
            if (
                permission in granted
                or self.permission_policy.operation_is_auto_granted(permission)
            ):
                continue
            permission_error = ToolError(
                "PERMISSION_REQUIRED",
                f"工具 {name} 的当前调用需要权限 {permission}。",
                "permission",
                False,
                {"permission": permission},
            )
            handled = self._handle_permission_required(
                name,
                arguments,
                permission_error,
                context=context,
                granted=granted,
                permission_context=permission_context,
            )
            if handled is not None:
                return handled
            return make_tool_result(
                name,
                {"ok": False, "error": permission_error.payload()},
            )
        permission_token = ACTIVE_PERMISSIONS.set(granted)
        request_context_token = ACTIVE_REQUEST_CONTEXT.set(context)
        try:
            try:
                payload = handler(arguments)
                payload.setdefault("ok", True)
                image_value = payload.pop("_image", None)
                if isinstance(image_value, tuple) and len(image_value) == 2:
                    image = (str(image_value[0]), str(image_value[1]))
            except ToolError as exc:
                handled = self._handle_permission_required(
                    name,
                    arguments,
                    exc,
                    context=context,
                    granted=granted,
                    permission_context=permission_context,
                )
                if handled is not None:
                    return handled
                payload = {"ok": False, "error": exc.payload()}
            except Exception as exc:
                # Keep unexpected implementation failures inside the tool result
                # boundary. Otherwise the HTTP transport can be interrupted and
                # clients only see an opaque ExceptionGroup/TaskGroup failure.
                LOGGER.exception("Unexpected failure while calling MCP tool %s", name)
                payload = {
                    "ok": False,
                    "error": {
                        "code": "INTERNAL_TOOL_ERROR",
                        "message": "unexpected tool failure",
                        "category": "runtime",
                        "retryable": True,
                        "details": {"exception_type": type(exc).__name__},
                    },
                }
        finally:
            ACTIVE_REQUEST_CONTEXT.reset(request_context_token)
            ACTIVE_PERMISSIONS.reset(permission_token)
        return make_tool_result(name, payload, image=image)

