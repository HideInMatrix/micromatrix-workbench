from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .mcp_connections import MCPConnectionDefinition


@dataclass(frozen=True, slots=True)
class EffectiveTool:
    provider: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    required_capabilities: tuple[str, ...] = ()
    required_operation_permissions: tuple[str, ...] = ()
    annotations: dict[str, bool] = field(default_factory=dict)
    connection_id: str = ""
    connection_name: str = ""
    connection_last_error: str = ""

    @property
    def key(self) -> str:
        if self.provider == "mcp":
            return f"mcp:{self.connection_id}:{self.tool_name}"
        return f"system:{self.tool_name}"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "key": self.key,
            "workflow_executable": True,
            "required_capabilities": list(self.required_capabilities),
            "required_operation_permissions": list(self.required_operation_permissions),
            "annotations": dict(self.annotations),
        }
        if self.provider == "mcp":
            payload["connection_id"] = self.connection_id
            payload["connection_name"] = self.connection_name
            payload["connection_last_error"] = self.connection_last_error
        return payload


def build_effective_tool_catalog(
    system_tools: Iterable[Any],
    connections: Iterable[MCPConnectionDefinition],
) -> tuple[EffectiveTool, ...]:
    values: list[EffectiveTool] = []
    for definition in system_tools:
        values.append(
            EffectiveTool(
                provider="system",
                tool_name=str(definition.name),
                description=str(definition.description),
                input_schema=dict(definition.input_schema),
                required_capabilities=tuple(sorted(item.value for item in definition.capabilities)),
                annotations={
                    "read_only": bool(definition.annotations.read_only),
                    "destructive": bool(definition.annotations.destructive),
                    "idempotent": bool(definition.annotations.idempotent),
                    "open_world": bool(definition.annotations.open_world),
                },
            )
        )
    for connection in connections:
        if not connection.enabled:
            continue
        for tool in connection.tools:
            values.append(
                EffectiveTool(
                    provider="mcp",
                    connection_id=connection.id,
                    connection_name=connection.name,
                    connection_last_error=connection.last_error,
                    tool_name=tool.name,
                    description=tool.description,
                    input_schema=dict(tool.input_schema),
                    required_capabilities=("process.execute",),
                    required_operation_permissions=(
                        ("network",)
                        if connection.transport == "http"
                        else ("privileged_executable",)
                    ),
                    annotations={
                        "read_only": bool(tool.annotations.get("readOnlyHint", False)),
                        "destructive": bool(tool.annotations.get("destructiveHint", False)),
                        "idempotent": bool(tool.annotations.get("idempotentHint", False)),
                        "open_world": bool(tool.annotations.get("openWorldHint", True)),
                    },
                )
            )
    return tuple(sorted(values, key=lambda item: item.key))

