from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..schemas import validate_value
from .mcp_connection_client import (
    MCPConnectionProbe,
    call_connection_tool,
    probe_connection,
)
from .mcp_connection_store import MCPConnectionStore
from .mcp_connections import MCPConnectionDefinition


class MCPConnectionService:
    def __init__(self, *, global_root: Path | None = None) -> None:
        self.store = MCPConnectionStore(global_root)

    def list(self) -> tuple[MCPConnectionDefinition, ...]:
        return self.store.list()

    def get(self, connection_id: str) -> MCPConnectionDefinition | None:
        return self.store.get(connection_id)

    def tool_keys(self) -> frozenset[str]:
        return frozenset(
            f"mcp:{connection.id}:{tool.name}"
            for connection in self.store.list()
            for tool in connection.tools
        )

    def validate(self, raw: Mapping[str, Any]) -> MCPConnectionDefinition:
        return MCPConnectionDefinition.from_mapping(raw)

    def save(
        self,
        raw: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> MCPConnectionDefinition:
        return self.store.save(
            self.validate(raw),
            expected_version=expected_version,
        )

    def delete(self, connection_id: str) -> bool:
        return self.store.delete(connection_id)

    def test(
        self,
        connection_id: str,
        *,
        timeout: float = 8.0,
        deep: bool = False,
    ) -> MCPConnectionProbe:
        definition = self.store.get(connection_id)
        if definition is None:
            raise KeyError(f"找不到 MCP Connection: {connection_id}")
        if not definition.enabled:
            raise ValueError("MCP Connection 已禁用")
        started = time.monotonic()
        probe = probe_connection(definition, discover_tools=deep, timeout=timeout)
        if not probe.ok:
            return replace(
                probe,
                health={
                    "transport": {"status": "error", "kind": definition.transport},
                    "protocol": {"status": "error"},
                    "discovery": {"status": "not_checked"},
                    "backend": {"status": "not_checked"},
                    "overall": "unavailable",
                },
            )
        health: dict[str, Any] = {
            "transport": {"status": "ok", "kind": definition.transport},
            "protocol": {"status": "ok", "version": probe.protocol_version},
            "discovery": (
                {"status": "ok", "tool_count": len(probe.tools)}
                if deep else {"status": "not_checked"}
            ),
            "backend": {"status": "not_checked"},
            "overall": "protocol_ready",
        }
        if not deep:
            return replace(probe, health=health)
        health_tool = definition.health_tool.strip()
        if not health_tool:
            health["backend"] = {
                "status": "unknown",
                "reason": "no_read_only_health_tool_configured",
            }
            health["overall"] = "protocol_ready_backend_unverified"
            return replace(probe, health=health)
        discovered = next((item for item in probe.tools if item.name == health_tool), None)
        if discovered is None:
            health["backend"] = {
                "status": "error",
                "tool": health_tool,
                "code": "MCP_HEALTH_TOOL_NOT_FOUND",
            }
            health["overall"] = "degraded"
            return replace(
                probe,
                ok=False,
                error=f"配置的 MCP health_tool 未发现: {health_tool}",
                health=health,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        if (
            discovered.annotations.get("readOnlyHint") is not True
            or discovered.annotations.get("destructiveHint") is True
        ):
            health["backend"] = {
                "status": "error",
                "tool": health_tool,
                "code": "MCP_HEALTH_TOOL_NOT_READ_ONLY",
            }
            health["overall"] = "degraded"
            return replace(
                probe,
                ok=False,
                error=f"MCP health_tool 必须声明 readOnlyHint 且不能是 destructive: {health_tool}",
                health=health,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        arguments = dict(definition.health_arguments)
        try:
            validate_value(arguments, discovered.input_schema)
            result = call_connection_tool(
                definition,
                health_tool,
                arguments,
                timeout=max(1.0, timeout),
            )
        except Exception as exc:
            health["backend"] = {
                "status": "error",
                "tool": health_tool,
                "code": "MCP_BACKEND_UNREACHABLE",
                "message": str(exc)[:1000],
            }
            health["overall"] = "degraded"
            return replace(
                probe,
                ok=False,
                error=str(exc),
                health=health,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        if bool(result.get("isError")):
            health["backend"] = {
                "status": "error",
                "tool": health_tool,
                "code": "MCP_BACKEND_HEALTH_FAILED",
            }
            health["overall"] = "degraded"
            return replace(
                probe,
                ok=False,
                error=f"MCP backend health tool returned isError: {health_tool}",
                health=health,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        health["backend"] = {"status": "ok", "tool": health_tool}
        health["overall"] = "ready"
        return replace(
            probe,
            health=health,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    def discover(
        self,
        connection_id: str,
        *,
        timeout: float = 8.0,
    ) -> tuple[MCPConnectionDefinition, MCPConnectionProbe]:
        current = self.store.get(connection_id)
        if current is None:
            raise KeyError(f"找不到 MCP Connection: {connection_id}")
        if not current.enabled:
            raise ValueError("MCP Connection 已禁用")
        probe = probe_connection(current, discover_tools=True, timeout=timeout)
        updated = replace(
            current,
            tools=probe.tools if probe.ok else current.tools,
            last_discovered_at=int(time.time()),
            last_error="" if probe.ok else probe.error,
        )
        persisted = self.store.save(updated, expected_version=current.version)
        return persisted, probe

    def call_tool(
        self,
        connection_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        definition = self.store.get(connection_id)
        if definition is None:
            raise KeyError(f"找不到 MCP Connection: {connection_id}")
        if not definition.enabled:
            raise ValueError("MCP Connection 已禁用")
        discovered = next(
            (item for item in definition.tools if item.name == tool_name),
            None,
        )
        if discovered is None:
            raise ValueError(
                f"MCP Tool 未发现或已失效: {connection_id}:{tool_name}"
            )
        validate_value(dict(arguments), discovered.input_schema)
        return call_connection_tool(
            definition,
            tool_name,
            arguments,
            timeout=timeout,
        )

