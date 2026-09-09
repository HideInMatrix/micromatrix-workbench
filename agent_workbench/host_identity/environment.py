from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent_workbench.runtime.process import hidden_process_kwargs


_ENV_MARKER = b"__MICROMATRIX_HOST_ENV_BEGIN__\0"


def _login_shell() -> str:
    if os.name == "nt":
        return str(os.environ.get("COMSPEC") or "cmd.exe")
    try:
        import pwd

        shell = str(pwd.getpwuid(os.getuid()).pw_shell or "").strip()
    except (ImportError, KeyError, OSError):
        shell = ""
    if not shell:
        shell = str(os.environ.get("SHELL") or "").strip()
    if not shell or not Path(shell).is_absolute() or not os.access(shell, os.X_OK):
        raise RuntimeError("无法确定当前用户登录 Shell，不能建立 Host identity environment。")
    return shell


def resolve_host_environment(workspace: Path) -> dict[str, str]:
    """Return the real desktop user's environment without exposing it to Runtime."""

    if os.name == "nt":
        return os.environ.copy()
    shell = _login_shell()
    completed = subprocess.run(
        [
            shell,
            "-lic",
            'printf "__MICROMATRIX_HOST_ENV_BEGIN__\\0"; command -p env -0',
        ],
        cwd=str(workspace),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=8,
        check=False,
        **hidden_process_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError("无法读取当前用户真实 Host identity environment。")
    marker = completed.stdout.rfind(_ENV_MARKER)
    if marker < 0:
        raise RuntimeError("Host identity environment 响应缺少边界标记。")
    payload = completed.stdout[marker + len(_ENV_MARKER) :]
    result: dict[str, str] = {}
    for record in payload.split(b"\0"):
        if not record or b"=" not in record:
            continue
        key, value = record.split(b"=", 1)
        try:
            name = key.decode("utf-8")
            rendered = value.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if name:
            result[name] = rendered
    return result


__all__ = ["resolve_host_environment"]
