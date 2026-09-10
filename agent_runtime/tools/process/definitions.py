from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition
from ...permissions.capabilities import Capability
from ...schemas import B, EXEC_COMMON, I, S, obj


PROCESS_TOOLS = (
    ToolDefinition(
        "exec_process",
        "Execute process",
        "Run a structured process without accepting a user-provided shell command string.",
        obj({"program": {**S, "minLength": 1}, "args": {"type": "array", "items": S, "default": []}, "workdir": {**S, "default": "."}, "cwd": S, "timeout_ms": {**I, "minimum": 1, "maximum": 600_000, "default": 30_000}, "yield_time_ms": {**I, "minimum": 0, "maximum": 30_000, "default": 10_000}, "stdin": {**S, "default": ""}, "tty": {**B, "default": False}, "env": {"type": "object", "additionalProperties": {"type": "string"}, "default": {}}, "use_host_identity": {**B, "default": False}, **EXEC_COMMON}, ("program",)),
        "exec_process",
        frozenset({Capability.PROCESS_EXECUTE}),
        ToolAnnotations(destructive=True, open_world=True),
    ),
    ToolDefinition(
        "exec_command",
        "Execute command",
        "Run a bounded command under the configured execution policy.",
        obj({"cmd": {**S, "minLength": 1}, "workdir": {**S, "default": "."}, "cwd": S, "timeout_ms": {**I, "minimum": 1, "maximum": 600_000, "default": 30_000}, "yield_time_ms": {**I, "minimum": 0, "maximum": 30_000, "default": 10_000}, "stdin": {**S, "default": ""}, "tty": {**B, "default": False}, "env": {"type": "object", "additionalProperties": {"type": "string"}, "default": {}}, **EXEC_COMMON}, ("cmd",)),
        "exec_command",
        frozenset({Capability.PROCESS_EXECUTE}),
        ToolAnnotations(destructive=True, open_world=True),
    ),
    ToolDefinition(
        "process_control",
        "Process control",
        "Manage a server-owned running command. action=write writes stdin or polls, action=kill terminates it, action=read_output reads retained stdout/stderr.",
        obj(
            {
                "action": {**S, "enum": ["write", "kill", "read_output"]},
                "command_id": S,
                "chars": {**S, "default": ""},
                "yield_time_ms": {**I, "minimum": 0, "maximum": 30_000, "default": 10_000},
                "signal": {**S, "enum": ["TERM", "KILL", "INT"], "default": "TERM"},
                "wait_ms": {**I, "minimum": 0, "maximum": 30_000, "default": 5_000},
                "kill_wait_ms": {**I, "minimum": 0, "maximum": 30_000, "default": 2_000},
                "output_ref": S,
                "stream": {**S, "enum": ["stdout", "stderr"]},
                "offset": {**I, "minimum": 0, "default": 0},
                "limit": {**I, "minimum": 1, "maximum": 1_048_576, "default": 4_096},
                **EXEC_COMMON,
            },
            ("action",),
        ),
        "process_control",
        frozenset({Capability.PROCESS_CONTROL}),
        ToolAnnotations(destructive=True),
    ),
)
