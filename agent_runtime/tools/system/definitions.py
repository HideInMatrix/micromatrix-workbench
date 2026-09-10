from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability, OperationPermission
from ...schemas import I, S, SA, obj


SYSTEM_TOOLS = (
    ToolDefinition(
        "server_info",
        "Server info",
        "Return a bounded server/contract summary. Use sections for targeted local diagnostics; Host details use host_status/host_diagnostics.",
        obj({
            "sections": {
                **SA,
                "items": {
                    **S,
                    "enum": ["permissions", "execution", "toolchains", "project", "tools"],
                },
                "maxItems": 5,
                "uniqueItems": True,
            },
        }),
        "server_info",
        frozenset({Capability.SYSTEM_INSPECT}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "check_exec_environment",
        "Check exec environment",
        "Return the effective command execution environment and safety policy.",
        obj(),
        "check_exec_environment",
        frozenset({Capability.SYSTEM_INSPECT}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "host_status",
        "Host status",
        "Return cached Desktop Host Supervisor/Worker connection state without invoking the Worker.",
        obj(),
        "host_status",
        frozenset({Capability.SYSTEM_INSPECT}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "host_diagnostics",
        "Host diagnostics",
        "Return bounded diagnostics for Workbench-owned Host Worker and providers.",
        obj({"max_events": {**I, "minimum": 1, "maximum": 50, "default": 20}}),
        "host_diagnostics",
        frozenset({Capability.SYSTEM_INSPECT}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "host_reconnect",
        "Reconnect Host",
        "Refresh this Runtime's Desktop Host handshake without restarting the Host Worker or replaying actions.",
        obj(),
        "host_reconnect",
        frozenset({Capability.SYSTEM_INSPECT}),
        ToolAnnotations(read_only=True, idempotent=True),
    ),
    ToolDefinition(
        "host_restart",
        "Restart Host Worker",
        "Restart only the Workbench-owned Desktop Host Worker. Requires independent host_manage approval.",
        obj(),
        "host_restart",
        frozenset({Capability.HOST_CAPABILITY_USE}),
        ToolAnnotations(destructive=True),
        operation_permissions=frozenset({OperationPermission.HOST_MANAGE}),
    ),
    ToolDefinition(
        "request_permissions",
        "Request permissions",
        "Request an explicit client-side permission confirmation when the client supports MCP elicitation; never silently escalates privileges.",
        obj(
            {
                "tool_name": {
                    **S,
                    "enum": [
                        "discover_toolchains",
                        "exec_process",
                        "exec_command",
                        "apply_patch",
                        "host_restart",
                    ],
                },
                "permission": {
                    **S,
                    "enum": [permission.value for permission in OperationPermission],
                },
                "reason": {**S, "minLength": 1},
                "arguments": {"type": "object", "additionalProperties": True},
                "scope": {**S, "enum": ["once", "session"], "default": "once"},
                "ttl_seconds": {**I, "minimum": 1, "maximum": 3_600, "default": 300},
            },
            ("tool_name", "permission", "reason", "arguments"),
        ),
        "request_permissions",
        frozenset({Capability.PERMISSION_MANAGE}),
        ToolAnnotations(read_only=True),
    ),
)
