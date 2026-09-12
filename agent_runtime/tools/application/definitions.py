from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition, ToolExecutionKind
from ...permissions.capabilities import Capability, OperationPermission
from ...schemas import B, I, S, obj

_HOST = ToolExecutionKind.HOST_CAPABILITY
_CAP = frozenset({Capability.HOST_CAPABILITY_USE})


def _branch(action: str, properties: dict | None = None, required: tuple[str, ...] = ()) -> dict:
    return obj({"action": {"type": "string", "const": action}, **(properties or {})}, ("action", *required))


def application_input_schema() -> dict:
    identity = {"name": S, "bundle_id": S}
    return {"type": "object", "oneOf": [
        _branch("resolve", identity),
        _branch("list", {"query": S, "max_results": {**I, "minimum": 1, "maximum": 100, "default": 30}}),
        _branch("launch", {"application_ref": {**S, "minLength": 8}, "new_instance": {**B, "default": False}}, ("application_ref",)),
        _branch("activate", {"application_ref": {**S, "minLength": 8}}, ("application_ref",)),
        _branch("quit", {"application_ref": {**S, "minLength": 8}}, ("application_ref",)),
    ]}


def application_permissions(arguments: dict) -> frozenset[OperationPermission]:
    action = str(arguments.get("action") or "")
    if action in {"launch", "activate"}:
        return frozenset({OperationPermission.APPLICATION_LAUNCH})
    if action == "quit":
        return frozenset({OperationPermission.APPLICATION_CONTROL})
    return frozenset()


def application_permission_variants() -> tuple[tuple[dict, tuple[OperationPermission, ...]], ...]:
    return (
        ({"action": "resolve"}, ()),
        ({"action": "list"}, ()),
        ({"action": "launch"}, (OperationPermission.APPLICATION_LAUNCH,)),
        ({"action": "activate"}, (OperationPermission.APPLICATION_LAUNCH,)),
        ({"action": "quit"}, (OperationPermission.APPLICATION_CONTROL,)),
    )


APPLICATION_TOOLS = (
    ToolDefinition(
        name="application",
        title="Desktop application lifecycle",
        description=("Resolve, list, launch, activate, or quit GUI applications through the Desktop Host. "
                     "First resolve/list to obtain an opaque application_ref, then use that ref for lifecycle actions. "
                     "Runtime never scans host application directories or guesses fixed installation paths."),
        input_schema=application_input_schema(),
        handler_name="application",
        capabilities=_CAP,
        annotations=ToolAnnotations(destructive=True, open_world=True),
        execution_kind=_HOST,
        preflight_handler_name="application_preflight",
        operation_permission_resolver=application_permissions,
        operation_permission_variants=application_permission_variants(),
    ),
)

__all__ = ["APPLICATION_TOOLS"]
