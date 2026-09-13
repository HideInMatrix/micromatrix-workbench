from __future__ import annotations

WORKBENCH_CONTROL_TOOL_PREFIXES = (
    "capability_",
    "skill_",
    "mcp_connection_",
)


def is_workbench_control_tool(tool_name: str) -> bool:
    """Return whether a Tool belongs to the Workbench authoring/control plane."""

    return tool_name.startswith(WORKBENCH_CONTROL_TOOL_PREFIXES)

