from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.tools import build_tool_registry
from agent_runtime.workbench import (
    CapabilityAssetService,
    MCPConnectionService,
    build_capability_catalog,
    build_effective_tool_catalog,
    capability_catalog_revision,
    is_workbench_control_tool,
    validate_capability_references,
)

class DesktopWorkbenchManager:
    def __init__(
        self,
        *,
        global_root: Path | None = None,
    ) -> None:
        self.global_root = global_root.resolve() if global_root is not None else None

    @staticmethod
    def _tool_names() -> set[str]:
        return {
            item.name
            for item in DesktopWorkbenchManager._system_tool_definitions()
        }

    @staticmethod
    def _system_tool_definitions():
        return tuple(
            item
            for item in build_tool_registry().definitions(enabled_features=frozenset({"view_image"}))
            if not is_workbench_control_tool(item.name)
        )

    def _mcp_connection_service(self) -> MCPConnectionService:
        return MCPConnectionService(global_root=self.global_root)

    def _global_asset_service(self) -> tuple[CapabilityAssetService, set[str]]:
        tool_names = self._tool_names()
        return CapabilityAssetService(global_root=self.global_root), tool_names

    def capability_catalog(self) -> dict[str, object]:
        assets, tools = self._global_asset_service()
        connections = self._mcp_connection_service().list()
        effective_tools = build_effective_tool_catalog(
            self._system_tool_definitions(),
            connections,
        )
        capabilities = build_capability_catalog(
            tools=effective_tools,
            skills=assets.skill_registry.list(),
        )
        return {
            "skills": [item.summary() for item in assets.skill_registry.list()],
            "tools": sorted(tools),
            "effective_tools": [item.to_dict() for item in effective_tools],
            "mcp_connections": [item.summary() for item in connections],
            "capabilities": list(capabilities),
            "revision": capability_catalog_revision(capabilities),
        }

    def get_mcp_connection(self, connection_id: str) -> dict[str, object]:
        definition = self._mcp_connection_service().get(connection_id.strip())
        if definition is None:
            raise KeyError(f"找不到 MCP Connection: {connection_id}")
        return definition.to_dict()

    def validate_mcp_connection(self, raw: dict[str, Any]) -> dict[str, object]:
        definition = self._mcp_connection_service().validate(raw)
        return {"ok": True, "connection": definition.to_dict()}

    def save_mcp_connection(
        self,
        raw: dict[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, object]:
        saved = self._mcp_connection_service().save(
            raw,
            expected_version=expected_version,
        )
        return {"ok": True, "saved": True, "connection": saved.to_dict()}

    def delete_mcp_connection(self, connection_id: str) -> bool:
        return self._mcp_connection_service().delete(connection_id.strip())

    def test_mcp_connection(
        self,
        connection_id: str,
        *,
        timeout_seconds: int = 8,
        deep: bool = False,
    ) -> dict[str, object]:
        probe = self._mcp_connection_service().test(
            connection_id.strip(),
            timeout=float(timeout_seconds),
            deep=bool(deep),
        )
        return {
            "ok": probe.ok,
            "connection_id": connection_id.strip(),
            "protocol_version": probe.protocol_version,
            "elapsed_ms": probe.elapsed_ms,
            "health": probe.health,
            "error": probe.error,
        }

    def discover_mcp_connection_tools(
        self,
        connection_id: str,
        *,
        timeout_seconds: int = 8,
    ) -> dict[str, object]:
        service = self._mcp_connection_service()
        persisted, probe = service.discover(
            connection_id.strip(),
            timeout=float(timeout_seconds),
        )
        effective_tools = build_effective_tool_catalog(
            self._system_tool_definitions(),
            service.list(),
        )
        return {
            "ok": probe.ok,
            "connection": persisted.to_dict(),
            "tools": [item.to_dict() for item in probe.tools],
            "effective_tools": [item.to_dict() for item in effective_tools],
            "protocol_version": probe.protocol_version,
            "elapsed_ms": probe.elapsed_ms,
            "error": probe.error,
        }

    def get_skill(self, skill_id: str) -> dict[str, object]:
        assets, _tool_names = self._global_asset_service()
        definition = assets.skill_registry.get(skill_id.strip())
        if definition is None:
            raise KeyError(f"找不到 Skill: {skill_id}")
        return definition.to_dict()

    def _validate_skill_capability_references(self, definition) -> None:
        catalog = self.capability_catalog()
        invalid = validate_capability_references(
            definition.recommended_capabilities,
            available_ids={str(item["id"]) for item in catalog["capabilities"]},
        )
        if invalid:
            raise ValueError(
                "Skill recommended_capabilities contains invalid or unavailable Capability IDs: "
                + ", ".join(invalid)
            )

    def validate_skill(self, raw: dict[str, Any]) -> dict[str, object]:
        assets, _tool_names = self._global_asset_service()
        definition = assets.validate_skill(raw)
        self._validate_skill_capability_references(definition)
        return {"ok": True, "skill": definition.to_dict()}

    def save_skill(
        self,
        raw: dict[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, object]:
        assets, _tool_names = self._global_asset_service()
        definition = assets.validate_skill(raw)
        self._validate_skill_capability_references(definition)
        saved = assets.save_skill(raw, expected_version=expected_version)
        return {"ok": True, "saved": True, "skill": saved.to_dict()}

    def delete_skill(self, skill_id: str) -> bool:
        assets, _tool_names = self._global_asset_service()
        return assets.delete_skill(skill_id.strip())


__all__ = ["DesktopWorkbenchManager"]
