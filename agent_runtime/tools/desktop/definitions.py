from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition, ToolExecutionKind
from ...permissions.capabilities import Capability
from .operations import (
    DESKTOP_OPERATIONS,
    desktop_input_schema,
    desktop_permission_variants,
    desktop_permissions,
)


_ACTIONS = ", ".join(item.action.value for item in DESKTOP_OPERATIONS)


DESKTOP_TOOLS = (
    ToolDefinition(
        name="desktop",
        title="Desktop computer use",
        description=(
            "Observe and control an explicitly bound desktop application window through the "
            "Workbench Desktop Host. Use action to select one operation: " + _ACTIONS + ". "
            "This is the general window/image/input capability for browsers, Blender, Figma, "
            "and other supported desktop applications; it does not expose application-specific "
            "document models."
        ),
        input_schema=desktop_input_schema(),
        handler_name="desktop",
        capabilities=frozenset({Capability.HOST_CAPABILITY_USE}),
        annotations=ToolAnnotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
        execution_kind=ToolExecutionKind.HOST_CAPABILITY,
        preflight_handler_name="desktop_preflight",
        operation_permission_resolver=desktop_permissions,
        operation_permission_variants=desktop_permission_variants(),
    ),
)


__all__ = ["DESKTOP_TOOLS"]
