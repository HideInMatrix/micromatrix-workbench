from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_runtime.toolchains.registration import normalize_program_name

from .process import hidden_process_kwargs


_MARKER = "__MICROMATRIX_HOST_TOOL__="
_RESOLVER_MARKER = "__MICROMATRIX_HOST_RESOLVER__="


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
        raise RuntimeError("无法确定当前用户的登录 Shell，不能解析主机工具路径。")
    return shell


def _resolved_workspace(workspace: str | Path | None) -> Path | None:
    if workspace is None or str(workspace).strip() == "":
        return None
    path = Path(workspace).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError("主机工具解析 Workspace 必须是存在的绝对目录。")
    return path.resolve()


def _workspace_python_environment(workspace: Path | None) -> Path | None:
    """Return one project-owned virtual environment without recursive scanning.

    A Python virtual environment is identified by ``pyvenv.cfg`` rather than a
    particular directory name. Only direct workspace children are considered.
    """
    if workspace is None:
        return None
    candidates: list[Path] = []
    try:
        entries = list(workspace.iterdir())[:256]
    except OSError:
        return None
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if not (entry / "pyvenv.cfg").is_file():
                continue
            entry.resolve(strict=True).relative_to(workspace)
        except (OSError, ValueError):
            continue
        candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            0 if item.name == ".venv" else 1 if item.name == "venv" else 2,
            item.name.casefold(),
        )
    )
    return candidates[0]


def _resolve_workspace_python(program: str, workspace: Path | None) -> dict[str, Any] | None:
    if program not in {"python", "python3"}:
        return None
    environment = _workspace_python_environment(workspace)
    if environment is None:
        return None
    bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    names = (program, "python3", "python") if program == "python" else (program, "python")
    for name in dict.fromkeys(names):
        filenames = (f"{name}.exe", name) if os.name == "nt" else (name,)
        for filename in filenames:
            path = bin_dir / filename
            try:
                if not path.is_file() or not os.access(path, os.X_OK):
                    continue
                path.resolve(strict=True)
            except OSError:
                continue
            return {
                "program": program,
                "executable": str(path),
                "resolver": "workspace_pyvenv",
                "shell": "",
                "shell_mode": "none",
                "shell_startup_files_evaluated": False,
                "workspace": str(workspace) if workspace is not None else "",
                "virtual_environment": str(environment),
            }
    return None


def _resolve_posix(program: str, workspace: Path | None) -> dict[str, Any]:
    shell = _login_shell()
    script = (
        'resolved=$(command -v "$1") || exit 127; '
        'canonical="$resolved"; resolver="login_shell_command_v"; '
        'if [ "$2" = "darwin" ]; then '
        'system_path=$(getconf PATH 2>/dev/null || true); '
        'system_resolved=""; developer_resolved=""; '
        'if [ -n "$system_path" ]; then '
        'system_resolved=$(PATH="$system_path" command -v "$1" 2>/dev/null || true); fi; '
        'if command -v xcrun >/dev/null 2>&1; then '
        'developer_resolved=$(xcrun --find "$1" 2>/dev/null || true); fi; '
        'if [ -n "$system_resolved" ] && [ "$resolved" = "$system_resolved" ] '
        '&& [ -n "$developer_resolved" ] && [ "$developer_resolved" != "$resolved" ]; then '
        'canonical="$developer_resolved"; resolver="apple_xcrun"; fi; fi; '
        'case "$canonical" in /*) '
        'printf "' + _MARKER + '%s\\n" "$canonical"; '
        'printf "' + _RESOLVER_MARKER + '%s\\n" "$resolver" ;; *) exit 126 ;; esac'
    )
    completed = subprocess.run(
        [
            shell,
            "-lic",
            script,
            "micromatrix-host-tool",
            program,
            "darwin" if sys.platform == "darwin" else "posix",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=8,
        check=False,
        env=os.environ.copy(),
        cwd=str(workspace) if workspace is not None else None,
        **hidden_process_kwargs(),
    )
    resolved = ""
    resolver = "login_shell_command_v"
    for line in completed.stdout.splitlines():
        if line.startswith(_MARKER):
            resolved = line[len(_MARKER):].strip()
        elif line.startswith(_RESOLVER_MARKER):
            resolver = line[len(_RESOLVER_MARKER):].strip() or resolver
    if completed.returncode or not resolved:
        raise RuntimeError(f"当前用户环境未找到工具 {program}。")
    path = Path(resolved).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"主机解析结果不是可执行文件: {resolved}")
    return {
        "program": program,
        "executable": str(path),
        "resolver": resolver,
        "shell": shell,
        "shell_mode": "login_interactive",
        "shell_startup_files_evaluated": True,
        "workspace": str(workspace) if workspace is not None else "",
    }


def _resolve_windows(program: str, workspace: Path | None) -> dict[str, Any]:
    comspec = _login_shell()
    completed = subprocess.run(
        [comspec, "/d", "/s", "/c", f"where {program}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=8,
        check=False,
        env=os.environ.copy(),
        cwd=str(workspace) if workspace is not None else None,
        **hidden_process_kwargs(),
    )
    candidates = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    path = Path(candidates[0]) if completed.returncode == 0 and candidates else None
    if path is None or not path.is_absolute() or not path.is_file():
        raise RuntimeError(f"当前用户环境未找到工具 {program}。")
    return {
        "program": program,
        "executable": str(path),
        "resolver": "where",
        "shell": comspec,
        "shell_startup_files_evaluated": False,
        "workspace": str(workspace) if workspace is not None else "",
    }


def resolve_host_tool(
    program: str,
    *,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve the executable the real desktop user environment would invoke.

    The Runtime never receives PATH, HOME, credentials, or shell output. Only the
    validated absolute executable path and minimal resolver metadata are returned.
    """

    normalized = normalize_program_name(program)
    resolved_workspace = _resolved_workspace(workspace)
    workspace_python = _resolve_workspace_python(normalized, resolved_workspace)
    if workspace_python is not None:
        return workspace_python
    return (
        _resolve_windows(normalized, resolved_workspace)
        if os.name == "nt"
        else _resolve_posix(normalized, resolved_workspace)
    )
