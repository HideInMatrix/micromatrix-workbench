"""Framework-level MCP tool definition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..permissions.capabilities import Capability, OperationPermission
from ..schemas import output_schema


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    open_world: bool = False


class ToolExecutionKind(StrEnum):
    """Where the concrete operation is executed.

    Runtime tools execute inside the Runtime process/sandbox boundary. Host
    capabilities are delegated to the trusted Workbench Desktop Host and are
    represented to the Runtime only through bounded, signed session operations.
    """

    RUNTIME = "runtime"
    HOST_CAPABILITY = "host_capability"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler_name: str
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)
    feature: str | None = None
    execution_kind: ToolExecutionKind = ToolExecutionKind.RUNTIME
    operation_permissions: frozenset[OperationPermission] = field(default_factory=frozenset)

    def mcp_definition(self, *, fake_readonly: bool = False) -> dict[str, Any]:
        annotations = self.annotations
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": output_schema(),
            "annotations": {
                "title": self.title,
                "readOnlyHint": True if fake_readonly else annotations.read_only,
                "destructiveHint": False if fake_readonly else annotations.destructive,
                "idempotentHint": annotations.idempotent,
                "openWorldHint": False if fake_readonly else annotations.open_world,
            },
        }
