from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability
from ...schemas import S, obj


TOOLCHAIN_TOOLS = (
    ToolDefinition(
        "discover_toolchains",
        "Discover toolchains",
        "Discover configured Node.js, Python, and Go toolchains. Missing programs are delegated to the Workbench Host for real-user command resolution, then require desktop confirmation before registration. Runtime never receives the host PATH, HOME, credentials, or shell output.",
        obj(
            {
                "kinds": {
                    "type": "array",
                    "items": {**S, "enum": ["node", "python", "go"]},
                    "default": ["node", "python", "go"],
                }
            }
        ),
        "discover_toolchains",
        frozenset({Capability.TOOLCHAIN_DISCOVER}),
        ToolAnnotations(read_only=False, idempotent=True),
    ),
)
