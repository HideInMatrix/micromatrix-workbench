from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability
from ...schemas import B, I, S, obj


SKILL_OBJECT = {"type": "object", "additionalProperties": True}
MCP_CONNECTION_OBJECT = {"type": "object", "additionalProperties": True}


WORKBENCH_TOOLS = (
    ToolDefinition(
        "capability_catalog",
        "Capability catalog",
        "Discover built-in tools, Skills, and external MCP tools exposed through this Workbench. The client AI decides whether and when to use a capability.",
        obj(
            {
                "types": {
                    "type": "array",
                    "items": {**S, "enum": ["builtin_tool", "skill", "mcp_tool"]},
                    "uniqueItems": True,
                },
                "query": S,
            }
        ),
        "capability_catalog",
        frozenset({Capability.FILESYSTEM_READ}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "capability_get",
        "Get capability",
        "Return one capability by stable capability_id, including its invocation contract and resource-specific detail when available.",
        obj(
            {
                "capability_id": {**S, "minLength": 1},
                "expected_revision": S,
            },
            ("capability_id",),
        ),
        "capability_get",
        frozenset({Capability.FILESYSTEM_READ}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "skill_manage",
        "Skill management",
        "Manage Workbench Skills through one domain tool. action=list|get|validate|save|delete.",
        obj(
            {
                "action": {**S, "enum": ["list", "get", "validate", "save", "delete"]},
                "skill_id": S,
                "skill": SKILL_OBJECT,
                "expected_version": {**I, "minimum": 0},
            },
            ("action",),
        ),
        "skill_manage",
        frozenset({Capability.FILESYSTEM_READ, Capability.FILESYSTEM_WRITE}),
        ToolAnnotations(destructive=True),
    ),
    ToolDefinition(
        "mcp_connection_manage",
        "MCP connection management",
        "Manage external MCP Connections. action=list|get|validate|save|delete|test|discover|call_tool.",
        obj(
            {
                "action": {**S, "enum": ["list", "get", "validate", "save", "delete", "test", "discover", "call_tool"]},
                "connection_id": S,
                "connection": MCP_CONNECTION_OBJECT,
                "expected_version": {**I, "minimum": 0},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
                "tool_name": S,
                "arguments": {"type": "object", "additionalProperties": True},
                "deep": B,
            },
            ("action",),
        ),
        "mcp_connection_manage",
        frozenset({Capability.FILESYSTEM_READ, Capability.FILESYSTEM_WRITE, Capability.PROCESS_EXECUTE}),
        ToolAnnotations(destructive=True, open_world=True),
    ),
)
