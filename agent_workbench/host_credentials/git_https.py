from __future__ import annotations

import os
import re
import secrets
import shlex
import subprocess
import time
import urllib.parse
from pathlib import Path

from agent_workbench.runtime.host_tools import resolve_host_tool
from agent_workbench.runtime.process import hidden_process_kwargs

from .base import HostCredentialError, HostCredentialSession


_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")


def _clean_https_url(value: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HostCredentialError("Host Credential Broker 当前仅支持 HTTPS Git remote。")
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise HostCredentialError("Git remote port 无效。") from exc
    if port:
        host = f"{host}:{port}"
    if not _HOST_RE.fullmatch(host):
        raise HostCredentialError("Git remote host 无效。")
    clean = urllib.parse.urlunsplit(("https", host, parsed.path or "/", "", ""))
    return clean, host


def _parse_credential_output(value: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in value.splitlines():
        if "=" not in line:
            continue
        key, item = line.split("=", 1)
        if key in {"username", "password"}:
            fields[key] = item
    username = fields.get("username", "")
    password = fields.get("password", "")
    if not username or not password or any(char in username for char in "\r\n\0"):
        raise HostCredentialError(
            "宿主 Git Credential Helper 没有返回可用于 HTTPS 的 username/password 凭据。"
        )
    return username, password


def _credential_fill(git: str, url: str, workspace: Path) -> tuple[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    completed = subprocess.run(
        [git, "-c", "credential.interactive=never", "credential", "fill"],
        input=f"url={url}\n\n",
        cwd=str(workspace),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=False,
        **hidden_process_kwargs(),
    )
    if completed.returncode != 0:
        raise HostCredentialError(
            "宿主 Git Credential Helper 无法提供该 remote 的凭据；请先在本机 Git 中登录。"
        )
    return _parse_credential_output(completed.stdout)


def _write_secret(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.write("\n")


def _posix_askpass(root: Path, host: str) -> tuple[Path, str]:
    path = root / "askpass.sh"
    host_literal = shlex.quote(host)
    root_literal = shlex.quote(str(root))
    script = f"""#!/bin/sh
prompt=${{1-}}
host={host_literal}
case "$prompt" in
  *"://$host/"*|*"://$host'"*|*"@$host/"*|*"@$host'"*) ;;
  *) exit 1 ;;
esac
case "$prompt" in
  *Username*|*username*) cat {root_literal}/username ;;
  *Password*|*password*) cat {root_literal}/password ;;
  *) exit 1 ;;
esac
"""
    path.write_text(script, encoding="utf-8")
    os.chmod(path, 0o500)
    return path, "posix_askpass"


def _windows_askpass(root: Path, host: str) -> tuple[Path, str]:
    path = root / "askpass.cmd"
    username_path = str(root / "username")
    password_path = str(root / "password")
    host_pattern = host.replace(".", r"\.").replace(":", r"\:")
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"echo %*| findstr /R /I /C:\"{host_pattern}['/:]\" >nul || exit /b 1\r\n"
        f'echo %*| findstr /I /C:"Username" >nul && type "{username_path}" && exit /b 0\r\n'
        f'echo %*| findstr /I /C:"Password" >nul && type "{password_path}" && exit /b 0\r\n'
        "exit /b 1\r\n"
    )
    path.write_text(script, encoding="utf-8")
    return path, "windows_cmd_askpass"


def prepare_git_https_session(
    *,
    broker_root: Path,
    server_id: str,
    operation: str,
    target_url: str,
    workspace: str | Path,
    ttl_seconds: int,
) -> tuple[HostCredentialSession, str]:
    if operation != "push":
        raise HostCredentialError("Git HTTPS Credential Broker 首版仅允许 push。")
    workdir = Path(workspace).expanduser().resolve()
    if not workdir.is_dir():
        raise HostCredentialError("Credential Broker workspace 不存在。")
    url, host = _clean_https_url(target_url)
    resolution = resolve_host_tool("git", workspace=workdir)
    # Credential lookup must never run inside the repository. A repository can
    # define credential.helper=!command in .git/config; executing `credential
    # fill` there would turn an untrusted Workspace config into Host code
    # execution. The broker root is deliberately outside every Workspace.
    username, password = _credential_fill(
        str(resolution["executable"]), url, broker_root
    )

    session_id = secrets.token_urlsafe(24)
    root = broker_root / session_id
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        _write_secret(root / "username", username)
        _write_secret(root / "password", password)
        askpass_path, helper = (
            _windows_askpass(root, host) if os.name == "nt" else _posix_askpass(root, host)
        )
    except Exception:
        import shutil

        shutil.rmtree(root, ignore_errors=True)
        raise
    session = HostCredentialSession(
        session_id=session_id,
        server_id=server_id,
        service="git_https",
        operation=operation,
        target_host=host,
        root=root,
        askpass_path=askpass_path,
        expires_at=int(time.time()) + max(15, min(int(ttl_seconds), 660)),
    )
    return session, helper
