from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...permissions.capabilities import OperationPermission
from ...schemas import B, I, S, obj
from .models import DesktopAction, DesktopMode


_SESSION_ID = {**S, "minLength": 8}
_OBSERVATION_ID = {**S, "minLength": 8}
_POST_OBSERVE = {
    "observe_after": {**B, "default": True},
    "max_elements": {**I, "minimum": 0, "maximum": 1000, "default": 200},
}
_POINT = obj(
    {
        "x": {**I, "minimum": 0},
        "y": {**I, "minimum": 0},
    },
    ("x", "y"),
)


def _branch(
    action: DesktopAction,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return obj(
        {
            "action": {"type": "string", "const": action.value},
            **(properties or {}),
        },
        ("action", *required),
    )


@dataclass(frozen=True, slots=True)
class DesktopOperationSpec:
    action: DesktopAction
    description: str
    schema_branches: tuple[dict[str, Any], ...]
    permissions: frozenset[OperationPermission] = frozenset()
    post_observe: bool = False


DESKTOP_OPERATIONS: tuple[DesktopOperationSpec, ...] = (
    DesktopOperationSpec(
        DesktopAction.TARGETS,
        "List a bounded set of selectable desktop application windows without exposing window contents.",
        (
            _branch(
                DesktopAction.TARGETS,
                {"max_results": {**I, "minimum": 1, "maximum": 100, "default": 30}},
            ),
        ),
    ),
    DesktopOperationSpec(
        DesktopAction.ATTACH,
        "Bind one explicit target window in observe or control mode.",
        (
            _branch(
                DesktopAction.ATTACH,
                {
                    "target_id": {**S, "minLength": 4},
                    "mode": {**S, "enum": [item.value for item in DesktopMode]},
                },
                ("target_id", "mode"),
            ),
        ),
    ),
    DesktopOperationSpec(
        DesktopAction.OBSERVE,
        "Capture one frame from the bound target and return coordinate/element metadata.",
        (
            _branch(
                DesktopAction.OBSERVE,
                {
                    "session_id": _SESSION_ID,
                    "max_elements": {**I, "minimum": 0, "maximum": 1000, "default": 200},
                },
                ("session_id",),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_OBSERVE}),
    ),
    DesktopOperationSpec(
        DesktopAction.CLICK,
        "Click a coordinate or accessibility element from the current desktop observation.",
        (
            _branch(
                DesktopAction.CLICK,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "x": {**I, "minimum": 0},
                    "y": {**I, "minimum": 0},
                    "button": {**S, "enum": ["left", "right", "middle"], "default": "left"},
                    "click_count": {**I, "minimum": 1, "maximum": 3, "default": 1},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "x", "y"),
            ),
            _branch(
                DesktopAction.CLICK,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "element_ref": {**S, "minLength": 1},
                    "button": {**S, "enum": ["left", "right", "middle"], "default": "left"},
                    "click_count": {**I, "minimum": 1, "maximum": 3, "default": 1},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "element_ref"),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_CONTROL}),
        True,
    ),
    DesktopOperationSpec(
        DesktopAction.TYPE,
        "Type text into the explicitly bound desktop target.",
        (
            _branch(
                DesktopAction.TYPE,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "text": {**S, "maxLength": 100_000},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "text"),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_CONTROL}),
        True,
    ),
    DesktopOperationSpec(
        DesktopAction.KEYPRESS,
        "Send a key or key combination to the explicitly bound desktop target.",
        (
            _branch(
                DesktopAction.KEYPRESS,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "key": {**S, "minLength": 1, "maxLength": 128},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "key"),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_CONTROL}),
        True,
    ),
    DesktopOperationSpec(
        DesktopAction.SCROLL,
        "Scroll inside the explicitly bound desktop target.",
        (
            _branch(
                DesktopAction.SCROLL,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "delta_x": {**I, "minimum": -100_000, "maximum": 100_000, "default": 0},
                    "delta_y": {**I, "minimum": -100_000, "maximum": 100_000},
                    "x": {**I, "minimum": 0},
                    "y": {**I, "minimum": 0},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "delta_y"),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_CONTROL}),
        True,
    ),
    DesktopOperationSpec(
        DesktopAction.DRAG,
        "Drag through a bounded path in the explicitly bound desktop target.",
        (
            _branch(
                DesktopAction.DRAG,
                {
                    "session_id": _SESSION_ID,
                    "observation_id": _OBSERVATION_ID,
                    "path": {
                        "type": "array",
                        "items": _POINT,
                        "minItems": 2,
                        "maxItems": 128,
                    },
                    "button": {**S, "enum": ["left", "right"], "default": "left"},
                    "duration_ms": {**I, "minimum": 0, "maximum": 10_000, "default": 300},
                    **_POST_OBSERVE,
                },
                ("session_id", "observation_id", "path"),
            ),
        ),
        frozenset({OperationPermission.DESKTOP_CONTROL}),
        True,
    ),
    DesktopOperationSpec(
        DesktopAction.DETACH,
        "Release this client's desktop session without closing the user's application.",
        (
            _branch(
                DesktopAction.DETACH,
                {"session_id": _SESSION_ID},
                ("session_id",),
            ),
        ),
    ),
)


_BY_ACTION = {item.action.value: item for item in DESKTOP_OPERATIONS}


def desktop_input_schema() -> dict[str, Any]:
    branches = [branch for item in DESKTOP_OPERATIONS for branch in item.schema_branches]
    return {"type": "object", "oneOf": branches}


def desktop_permissions(arguments: dict[str, Any]) -> frozenset[OperationPermission]:
    action = str(arguments.get("action") or "")
    spec = _BY_ACTION.get(action)
    if spec is None:
        return frozenset()
    permissions = set(spec.permissions)
    if action == DesktopAction.ATTACH.value:
        mode = str(arguments.get("mode") or "")
        if mode == DesktopMode.OBSERVE.value:
            permissions.add(OperationPermission.DESKTOP_OBSERVE)
        elif mode == DesktopMode.CONTROL.value:
            permissions.add(OperationPermission.DESKTOP_CONTROL)
    if spec.post_observe and bool(arguments.get("observe_after", True)):
        permissions.add(OperationPermission.DESKTOP_OBSERVE)
    return frozenset(permissions)


def desktop_permission_variants() -> tuple[
    tuple[str, tuple[OperationPermission, ...]], ...
]:
    values: list[tuple[str, tuple[OperationPermission, ...]]] = []
    for spec in DESKTOP_OPERATIONS:
        permissions = set(spec.permissions)
        if spec.action == DesktopAction.ATTACH:
            permissions.update(
                {
                    OperationPermission.DESKTOP_OBSERVE,
                    OperationPermission.DESKTOP_CONTROL,
                }
            )
        if spec.post_observe:
            permissions.add(OperationPermission.DESKTOP_OBSERVE)
        values.append(
            (
                spec.action.value,
                tuple(sorted(permissions, key=lambda item: item.value)),
            )
        )
    return tuple(values)


__all__ = [
    "DESKTOP_OPERATIONS",
    "DesktopOperationSpec",
    "desktop_input_schema",
    "desktop_permission_variants",
    "desktop_permissions",
]
