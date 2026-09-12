from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition, ToolExecutionKind
from ...permissions.capabilities import Capability, OperationPermission
from ...schemas import I, S, obj

_HOST = ToolExecutionKind.HOST_CAPABILITY

ARTIFACT_TOOLS = (
    ToolDefinition(
        "host_artifact_import",
        "Import Host artifact",
        "Import a bounded file produced in the Desktop Host OS temporary directory. Image artifacts are returned inline; non-image artifacts require a workspace destination. The bridge never reads arbitrary Host paths and authorization is not persistent.",
        obj(
            {
                "host_path": {**S, "minLength": 1},
                "destination": S,
                "max_bytes": {**I, "minimum": 1, "maximum": 50 * 1024 * 1024, "default": 25 * 1024 * 1024},
            },
            ("host_path",),
        ),
        "host_artifact_import",
        frozenset({Capability.HOST_CAPABILITY_USE}),
        ToolAnnotations(idempotent=True, open_world=True),
        execution_kind=_HOST,
        preflight_handler_name="host_artifact_import_preflight",
        operation_permissions=frozenset({OperationPermission.HOST_ARTIFACT_READ}),
    ),
)
