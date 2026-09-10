from __future__ import annotations

import os
import re

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)


_SENSITIVE_ENV_RE = re.compile(
    r"(token|secret|password|passwd|credential|api[_-]?key|private|access[_-]?key|auth)",
    re.I,
)
_INJECTION_ENV_RE = re.compile(
    r"^(?:DYLD_|LD_PRELOAD$|LD_LIBRARY_PATH$|PYTHONHOME$|PYTHONPATH$|NODE_OPTIONS$|RUBYOPT$|PERL5OPT$)",
    re.I,
)
_PROCESS_LOCAL_ENV = {
    "__CFBundleIdentifier",
    "COMMAND_MODE",
    "PWD",
    "OLDPWD",
    "SHLVL",
    "_",
    "XPC_FLAGS",
    "XPC_SERVICE_NAME",
}


def host_user_session_environment() -> tuple[dict[str, str], tuple[str, ...]]:
    """Build a host-user session environment without Runtime/broker internals.

    Host applications keep the real user/session locations (HOME, TMPDIR, GUI
    session variables, etc.). We only remove values that belong to the parent
    Workbench process itself, code-injection variables, and obvious secrets.
    """

    env: dict[str, str] = {}
    redactions: list[str] = []
    for key, value in os.environ.items():
        if key in {BROKER_DIR_ENV, BROKER_SECRET_ENV, BROKER_SERVER_ID_ENV}:
            continue
        if key.startswith("AGENT_RUNTIME_") or key in _PROCESS_LOCAL_ENV:
            continue
        if _INJECTION_ENV_RE.search(key):
            continue
        if _SENSITIVE_ENV_RE.search(key):
            if len(value) >= 6 and value not in redactions:
                redactions.append(value)
            continue
        env[key] = value
    return env, tuple(sorted(redactions, key=len, reverse=True))


__all__ = ["host_user_session_environment"]
