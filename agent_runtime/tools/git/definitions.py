from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability
from ...schemas import B, I, S, SA, obj


_READ_ONLY = ToolAnnotations(read_only=True, idempotent=True)

GIT_TOOLS = (
    ToolDefinition(
        "git_inspect",
        "Git inspect",
        "Inspect Git state through one domain tool. action=status|diff|log|show|blame; pass the same fields accepted by the corresponding internal Git operation.",
        obj(
            {
                "action": {**S, "enum": ["status", "diff", "log", "show", "blame"]},
                "path": S,
                "paths": SA,
                "include_untracked": B,
                "max_entries": I,
                "staged": B,
                "unstaged": B,
                "context_lines": I,
                "max_bytes": I,
                "ref": S,
                "max_count": I,
                "skip": I,
                "rev": S,
                "include_diff": B,
                "start_line": I,
                "end_line": I,
                "max_lines": I,
            },
            ("action",),
        ),
        "git_inspect",
        frozenset({Capability.GIT_READ}),
        _READ_ONLY,
    ),
)
