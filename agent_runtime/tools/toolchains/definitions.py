from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability
from ...schemas import S, obj


TOOLCHAIN_TOOLS = (
    ToolDefinition(
        "discover_toolchains",
        "Discover toolchains",
        "Discover configured Node.js, Python, and Go toolchains. Missing supported programs use the same desktop-confirmed registration as execution; no login shell or temporary Home access. Reports missing programs and registration errors explicitly.",
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
