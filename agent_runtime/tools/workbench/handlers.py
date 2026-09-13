from __future__ import annotations

import base64
import binascii
from typing import Any

from ...errors import ToolError
from ...workbench.capability_catalog import (
    build_capability_catalog,
    capability_catalog_revision,
    filter_capability_catalog,
    validate_capability_references,
)
from ...workbench.effective_tools import build_effective_tool_catalog
from ...workbench.mcp_connection_store import MCPConnectionVersionConflictError
from ...workbench.skill_store import SkillVersionConflictError
from ...workbench.tool_references import is_workbench_control_tool


def _contains_plain_secret(value: Any, *, parent_key: str = "") -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized.endswith("_ref"):
                continue
            if any(marker in normalized for marker in ("password", "secret", "token", "api_key", "apikey")):
                if item is not None and item != "" and item is not False:
                    return True
            if _contains_plain_secret(item, parent_key=normalized):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_plain_secret(item, parent_key=parent_key) for item in value)
    return False


class WorkbenchHandlers:
    def _refresh_capability_assets(self) -> None:
        assets = getattr(self, "capability_assets", None)
        if assets is not None:
            assets.refresh()

    def _current_capabilities(self) -> tuple[dict[str, Any], ...]:
        self._refresh_capability_assets()
        system_tools = [
            definition
            for definition in self._tools
            if not is_workbench_control_tool(definition.name)
        ]
        effective_tools = build_effective_tool_catalog(
            system_tools,
            self.mcp_connections.list(),
        )
        return build_capability_catalog(
            tools=effective_tools,
            skills=self.skill_registry.list(),
        )

    def capability_catalog(self, arguments: dict[str, Any]) -> dict[str, Any]:
        current = self._current_capabilities()
        capabilities = filter_capability_catalog(
            current,
            types=arguments.get("types") or (),
            query=str(arguments.get("query") or ""),
        )
        return {
            "schema_version": 1,
            "decision_owner": "ai_client",
            "routing": "descriptive_only",
            "revision": capability_catalog_revision(current),
            "capabilities": list(capabilities),
            "count": len(capabilities),
            "ok": True,
        }

    def capability_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(arguments.get("capability_id") or "").strip()
        current = self._current_capabilities()
        revision = capability_catalog_revision(current)
        expected_revision = str(arguments.get("expected_revision") or "").strip()
        if expected_revision and expected_revision != revision:
            return {
                "schema_version": 1,
                "decision_owner": "ai_client",
                "capability_id": capability_id,
                "capability": None,
                "revision": revision,
                "expected_revision": expected_revision,
                "ok": False,
                "error": "CAPABILITY_CATALOG_CHANGED",
            }
        capability = next(
            (item for item in current if item["id"] == capability_id),
            None,
        )
        if capability is None:
            return {
                "capability_id": capability_id,
                "capability": None,
                "revision": revision,
                "ok": False,
                "error": "CAPABILITY_NOT_FOUND",
            }

        detail: dict[str, Any] | None = None
        if capability["type"] == "skill":
            skill_id = str(capability["source"]["skill_id"])
            skill = self.skill_registry.get(skill_id)
            detail = skill.to_dict() if skill is not None else None

        return {
            "schema_version": 1,
            "decision_owner": "ai_client",
            "revision": revision,
            "capability": capability,
            "detail": detail,
            "impact": {
                "required_dependents": [
                    item
                    for item in capability.get("dependents", [])
                    if item.get("required")
                ],
                "soft_dependents": [
                    item
                    for item in capability.get("dependents", [])
                    if not item.get("required")
                ],
            },
            "ok": True,
        }

    def _required_capability_dependents(self, capability_ids: set[str]) -> list[dict[str, Any]]:
        affected: list[dict[str, Any]] = []
        for capability in self._current_capabilities():
            for dependency in capability.get("dependencies", []):
                if not dependency.get("required"):
                    continue
                if str(dependency.get("capability_id") or "") not in capability_ids:
                    continue
                affected.append(
                    {
                        "dependent_capability_id": capability["id"],
                        "dependency_capability_id": dependency["capability_id"],
                        "relation": dependency.get("relation", "depends_on"),
                    }
                )
        return affected

    def skill_list(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_capability_assets()
        skills = self.skill_registry.list()
        return {
            "skills": [item.summary() for item in skills],
            "count": len(skills),
            "ok": True,
        }

    def skill_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_capability_assets()
        skill_id = str(arguments.get("skill_id") or "").strip()
        skill = self.skill_registry.get(skill_id)
        if skill is None:
            raise ToolError("SKILL_NOT_FOUND", f"找不到 Skill: {skill_id}")
        return {"skill": skill.to_dict(), "ok": True}

    def _parse_skill(self, arguments: dict[str, Any]):
        raw = arguments.get("skill")
        if not isinstance(raw, dict):
            raise ToolError("SKILL_INVALID", "skill must be an object")
        if _contains_plain_secret(raw):
            raise ToolError(
                "SKILL_SECRET",
                "Skill 不能保存 Password/Token/Secret/API Key 明文；请使用引用或移除敏感值。",
            )
        try:
            skill = self.capability_assets.validate_skill(raw)
        except (TypeError, ValueError) as exc:
            raise ToolError("SKILL_INVALID", f"Skill 定义无效: {exc}") from exc
        invalid_refs = validate_capability_references(
            skill.recommended_capabilities,
            available_ids={str(item["id"]) for item in self._current_capabilities()},
        )
        if invalid_refs:
            raise ToolError(
                "SKILL_CAPABILITY_REFERENCE_INVALID",
                "Skill recommended_capabilities 包含不存在或格式无效的 Capability ID。",
                category="validation",
                details={"invalid_capability_ids": list(invalid_refs)},
            )
        return skill

    def skill_validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_capability_assets()
        skill = self._parse_skill(arguments)
        return {"skill": skill.to_dict(), "ok": True}

    def skill_save(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_capability_assets()
        skill = self._parse_skill(arguments)
        expected_version = int(arguments.get("expected_version", 0))
        try:
            saved = self.capability_assets.save_skill(
                skill.to_dict(),
                expected_version=expected_version,
            )
        except SkillVersionConflictError as exc:
            raise ToolError(
                "SKILL_VERSION_CONFLICT",
                str(exc),
                category="conflict",
                details={
                    "skill_id": exc.skill_id,
                    "expected_version": exc.expected,
                    "actual_version": exc.actual,
                },
            ) from exc
        return {"saved": True, "skill": saved.to_dict(), "ok": True}

    def skill_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_capability_assets()
        skill_id = str(arguments.get("skill_id") or "").strip()
        affected = self._required_capability_dependents({f"skill:{skill_id}"})
        if affected:
            raise ToolError(
                "CAPABILITY_DEPENDENCY_CONFLICT",
                "Skill 被其他必需 Capability 引用，删除会破坏现有能力关系。",
                category="conflict",
                details={"dependents": affected},
            )
        try:
            deleted = self.capability_assets.delete_skill(skill_id)
        except ValueError as exc:
            raise ToolError("SKILL_INVALID_ID", str(exc)) from exc
        return {"skill_id": skill_id, "deleted": deleted, "ok": True}

    def skill_manage(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        payload = {key: value for key, value in arguments.items() if key != "action"}
        handlers = {
            "list": self.skill_list,
            "get": self.skill_get,
            "validate": self.skill_validate,
            "save": self.skill_save,
            "delete": self.skill_delete,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ToolError("INVALID_ARGUMENT", f"unsupported skill_manage action: {action}", "validation")
        return handler(payload)

    def _mcp_connection_definition(self, connection_id: str):
        definition = self.mcp_connections.get(connection_id)
        if definition is None:
            raise ToolError(
                "MCP_CONNECTION_NOT_FOUND",
                f"找不到 MCP Connection: {connection_id}",
            )
        return definition

    def _require_mcp_connection_access(self, definition, *, operation: str) -> None:
        if definition.transport == "http":
            if not self._permission_granted("network"):
                raise ToolError(
                    "PERMISSION_REQUIRED",
                    f"{operation} 需要访问外部 MCP 网络端点。",
                    category="permission",
                    details={"permission": "network"},
                )
            return
        if not self._permission_granted("privileged_executable"):
            raise ToolError(
                "PERMISSION_REQUIRED",
                f"{operation} 需要启动用户配置的 stdio MCP 进程。",
                category="permission",
                details={"permission": "privileged_executable"},
            )

    def mcp_connection_list(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        definitions = self.mcp_connections.list()
        return {
            "connections": [item.summary() for item in definitions],
            "count": len(definitions),
            "ok": True,
        }

    def mcp_connection_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(arguments.get("connection_id") or "").strip()
        definition = self._mcp_connection_definition(connection_id)
        return {"connection": definition.to_dict(), "ok": True}

    def mcp_connection_validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("connection")
        if not isinstance(raw, dict):
            raise ToolError("MCP_CONNECTION_INVALID", "connection must be an object")
        try:
            definition = self.mcp_connections.validate(raw)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                "MCP_CONNECTION_INVALID",
                f"MCP Connection 定义无效: {exc}",
            ) from exc
        return {"connection": definition.to_dict(), "ok": True}

    def mcp_connection_save(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("connection")
        if not isinstance(raw, dict):
            raise ToolError("MCP_CONNECTION_INVALID", "connection must be an object")
        expected_version = int(arguments.get("expected_version", 0))
        try:
            saved = self.mcp_connections.save(raw, expected_version=expected_version)
        except MCPConnectionVersionConflictError as exc:
            raise ToolError(
                "MCP_CONNECTION_VERSION_CONFLICT",
                str(exc),
                category="conflict",
                details={
                    "connection_id": exc.connection_id,
                    "expected_version": exc.expected,
                    "actual_version": exc.actual,
                },
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ToolError("MCP_CONNECTION_INVALID", str(exc)) from exc
        return {"connection": saved.to_dict(), "saved": True, "ok": True}

    def mcp_connection_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(arguments.get("connection_id") or "").strip()
        self._refresh_capability_assets()
        capability_ids = {
            str(item["id"])
            for item in self._current_capabilities()
            if str(item["id"]).startswith(f"mcp:{connection_id}:")
        }
        affected = self._required_capability_dependents(capability_ids)
        if affected:
            raise ToolError(
                "CAPABILITY_DEPENDENCY_CONFLICT",
                "MCP Connection 提供的 Tool 被其他必需 Capability 引用，删除会破坏现有能力关系。",
                category="conflict",
                details={"dependents": affected},
            )
        try:
            deleted = self.mcp_connections.delete(connection_id)
        except ValueError as exc:
            raise ToolError("MCP_CONNECTION_INVALID_ID", str(exc)) from exc
        return {"connection_id": connection_id, "deleted": deleted, "ok": True}

    def mcp_connection_test(self, arguments: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(arguments.get("connection_id") or "").strip()
        definition = self._mcp_connection_definition(connection_id)
        self._require_mcp_connection_access(definition, operation="MCP Connection Test")
        nested_arguments = arguments.get("arguments")
        nested_deep = (
            nested_arguments.get("deep")
            if isinstance(nested_arguments, dict) and "deep" in nested_arguments
            else None
        )
        deep = (
            bool(arguments.get("deep"))
            if "deep" in arguments
            else bool(nested_deep)
            if nested_deep is not None
            else bool(definition.health_tool.strip())
        )
        probe = self.mcp_connections.test(
            connection_id,
            timeout=float(arguments.get("timeout_seconds", 8)),
            deep=deep,
        )
        if not probe.ok:
            backend = probe.health.get("backend") if isinstance(probe.health, dict) else None
            failure_code = (
                str(backend.get("code") or "")
                if isinstance(backend, dict)
                else ""
            )
            raise ToolError(
                failure_code or "MCP_CONNECTION_TEST_FAILED",
                probe.error or "MCP Connection Test failed",
                retryable=True,
                details={"health": probe.health},
            )
        return {
            "connection_id": connection_id,
            "protocol_version": probe.protocol_version,
            "elapsed_ms": probe.elapsed_ms,
            "health": probe.health,
            "ok": True,
        }

    def mcp_connection_discover_tools(self, arguments: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(arguments.get("connection_id") or "").strip()
        definition = self._mcp_connection_definition(connection_id)
        self._require_mcp_connection_access(definition, operation="MCP Tool Discovery")
        persisted, probe = self.mcp_connections.discover(
            connection_id,
            timeout=float(arguments.get("timeout_seconds", 8)),
        )
        if not probe.ok:
            raise ToolError(
                "MCP_TOOL_DISCOVERY_FAILED",
                probe.error or "MCP Tool discovery failed",
                retryable=True,
                details={"connection": persisted.summary()},
            )
        effective = build_effective_tool_catalog(
            [
                item
                for item in self._tools
                if not is_workbench_control_tool(item.name)
            ],
            self.mcp_connections.list(),
        )
        return {
            "connection": persisted.to_dict(),
            "tools": [item.to_dict() for item in probe.tools],
            "effective_tools": [item.to_dict() for item in effective],
            "protocol_version": probe.protocol_version,
            "elapsed_ms": probe.elapsed_ms,
            "ok": True,
        }

    def mcp_connection_call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(arguments.get("connection_id") or "").strip()
        tool_name = str(arguments.get("tool_name") or "").strip()
        tool_arguments = arguments.get("arguments")
        if not isinstance(tool_arguments, dict):
            raise ToolError("MCP_TOOL_ARGUMENTS_INVALID", "arguments must be an object")
        definition = self._mcp_connection_definition(connection_id)
        self._require_mcp_connection_access(
            definition,
            operation=f"MCP Tool {tool_name}",
        )
        try:
            result = self.mcp_connections.call_tool(
                connection_id,
                tool_name,
                tool_arguments,
                timeout=float(arguments.get("timeout_seconds", 30)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError("MCP_TOOL_INVALID", str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                "MCP_TOOL_CALL_FAILED",
                str(exc),
                retryable=True,
            ) from exc
        payload = {
            "connection_id": connection_id,
            "tool_name": tool_name,
            "result": result,
            "ok": not bool(result.get("isError")),
        }
        content = result.get("content")
        if isinstance(content, list):
            sanitized: list[Any] = []
            attached = False
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "image":
                    sanitized.append(item)
                    continue
                encoded = str(item.get("data") or "")
                mime_type = str(item.get("mimeType") or item.get("mime_type") or "image/png")
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError):
                    sanitized.append({"type": "image", "mimeType": mime_type, "invalid": True})
                    continue
                if len(data) > 25 * 1024 * 1024:
                    raise ToolError("OUTPUT_TOO_LARGE", "External MCP image 超过 25 MiB 限制。", "runtime")
                sanitized.append({"type": "image", "mimeType": mime_type, "bytes": len(data), "data_omitted": True})
                if not attached:
                    payload["_image"] = (mime_type, encoded)
                    attached = True
            payload["result"] = {**result, "content": sanitized}
        return payload

    def mcp_connection_manage(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        payload = {key: value for key, value in arguments.items() if key != "action"}
        handlers = {
            "list": self.mcp_connection_list,
            "get": self.mcp_connection_get,
            "validate": self.mcp_connection_validate,
            "save": self.mcp_connection_save,
            "delete": self.mcp_connection_delete,
            "test": self.mcp_connection_test,
            "discover": self.mcp_connection_discover_tools,
            "call_tool": self.mcp_connection_call_tool,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ToolError("INVALID_ARGUMENT", f"unsupported mcp_connection_manage action: {action}", "validation")
        return handler(payload)
