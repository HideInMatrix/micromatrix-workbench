from __future__ import annotations

import hashlib
import http.client
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..core.resources import is_frozen
from ..core.settings import settings_dir
from .release import _github_ssl_context


UPDATE_DOWNLOAD_ATTEMPTS = 3
UPDATE_TIMEOUT_SECONDS = 20.0
MAX_CHECKSUM_BYTES = 16 * 1024


def current_install_target() -> Path:
    """Return the replaceable application root for a frozen desktop build."""

    if not is_frozen():
        raise RuntimeError("应用内更新只支持已打包的桌面程序。")

    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for candidate in (executable, *executable.parents):
            if candidate.suffix.lower() == ".app":
                if len(candidate.parts) >= 2 and candidate.parts[1] == "Volumes":
                    raise RuntimeError(
                        "当前程序仍从 DMG 中运行。请先拖入 Applications，再使用应用内更新。"
                    )
                return candidate
        raise RuntimeError("无法定位当前 macOS .app 安装目录。")
    if sys.platform.startswith("win"):
        return executable
    return executable.parent


def _parse_checksum(raw: str, expected_filename: str) -> str:
    line = raw.strip().splitlines()[0] if raw.strip() else ""
    parts = line.split()
    if not parts or len(parts[0]) != 64:
        raise ValueError("更新包 SHA-256 文件格式无效。")
    digest = parts[0].lower()
    if any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("更新包 SHA-256 文件格式无效。")
    if len(parts) >= 2:
        filename = parts[-1].lstrip("*")
        if filename != expected_filename:
            raise ValueError("SHA-256 文件与当前平台更新包不匹配。")
    return digest


def download_checksum(url: str, expected_filename: str) -> str:
    last_error: BaseException | None = None
    for attempt in range(1, UPDATE_DOWNLOAD_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/plain, application/octet-stream;q=0.9",
                "User-Agent": "MicroMatrix-Workbench-Updater",
                "Connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=UPDATE_TIMEOUT_SECONDS,
                context=_github_ssl_context(),
            ) as response:
                raw = response.read(MAX_CHECKSUM_BYTES + 1)
            if len(raw) > MAX_CHECKSUM_BYTES:
                raise ValueError("更新包 SHA-256 文件过大。")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("更新包 SHA-256 文件不是 UTF-8 文本。") from exc
            return _parse_checksum(text, expected_filename)
        except urllib.error.HTTPError:
            raise
        except (
            http.client.IncompleteRead,
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            last_error = exc
            if attempt >= UPDATE_DOWNLOAD_ATTEMPTS:
                break
            time.sleep(0.25 * attempt)
    raise RuntimeError("无法下载更新包 SHA-256 校验文件，请检查网络后重试。") from last_error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _helper_log_path() -> Path:
    path = settings_dir() / "update-helper.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_helper_script(suffix: str, content: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix="micromatrix-workbench-updater-",
        suffix=suffix,
        text=True,
    )
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        if os.name != "nt":
            path.chmod(0o700)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


_POSIX_MAC_HELPER = r'''#!/bin/sh
set -eu
ARCHIVE="$1"
TARGET="$2"
PARENT_PID="$3"

while kill -0 "$PARENT_PID" 2>/dev/null; do
  sleep 0.25
done

STAGING="$(mktemp -d -t micromatrix-workbench-update.XXXXXX)"
BACKUP="${TARGET}.micromatrix-workbench-update-backup"

rollback() {
  if [ -d "$BACKUP" ]; then
    rm -rf "$TARGET" 2>/dev/null || true
    mv "$BACKUP" "$TARGET" 2>/dev/null || true
  fi
}

trap 'rollback; rm -rf "$STAGING" 2>/dev/null || true' INT TERM HUP

/usr/bin/ditto -x -k "$ARCHIVE" "$STAGING"
SOURCE="$STAGING/$(basename "$TARGET")"
if [ ! -d "$SOURCE" ]; then
  echo "Updater: extracted app bundle not found: $SOURCE" >&2
  rm -rf "$STAGING"
  /usr/bin/open "$TARGET" >/dev/null 2>&1 || true
  exit 20
fi

rm -rf "$BACKUP"
if ! mv "$TARGET" "$BACKUP"; then
  echo "Updater: failed to move current app bundle to backup" >&2
  rm -rf "$STAGING"
  /usr/bin/open "$TARGET" >/dev/null 2>&1 || true
  exit 22
fi
if ! /usr/bin/ditto "$SOURCE" "$TARGET"; then
  echo "Updater: failed to install new app bundle" >&2
  rollback
  rm -rf "$STAGING"
  /usr/bin/open "$TARGET" >/dev/null 2>&1 || true
  exit 21
fi

rm -rf "$STAGING"
rm -f "$ARCHIVE"
rmdir "$(dirname "$ARCHIVE")" 2>/dev/null || true

if ! /usr/bin/open "$TARGET"; then
  echo "Updater: new app was installed but automatic restart failed" >&2
fi

sleep 2
rm -rf "$BACKUP"
rm -f "$0"
exit 0
'''


_POSIX_LINUX_HELPER = r'''#!/bin/sh
set -eu
ARCHIVE="$1"
TARGET="$2"
PARENT_PID="$3"
EXEC_NAME="$4"

while kill -0 "$PARENT_PID" 2>/dev/null; do
  sleep 0.25
done

STAGING="$(mktemp -d -t micromatrix-workbench-update.XXXXXX)"
BACKUP="${TARGET}.micromatrix-workbench-update-backup"

rollback() {
  if [ -d "$BACKUP" ]; then
    rm -rf "$TARGET" 2>/dev/null || true
    mv "$BACKUP" "$TARGET" 2>/dev/null || true
  fi
}

trap 'rollback; rm -rf "$STAGING" 2>/dev/null || true' INT TERM HUP

tar -xzf "$ARCHIVE" -C "$STAGING"
SOURCE="$STAGING/$(basename "$TARGET")"
if [ ! -d "$SOURCE" ]; then
  echo "Updater: extracted application directory not found: $SOURCE" >&2
  rm -rf "$STAGING"
  "$TARGET/$EXEC_NAME" >/dev/null 2>&1 &
  exit 20
fi

rm -rf "$BACKUP"
if ! mv "$TARGET" "$BACKUP"; then
  echo "Updater: failed to move current application to backup" >&2
  rm -rf "$STAGING"
  "$TARGET/$EXEC_NAME" >/dev/null 2>&1 &
  exit 22
fi
if ! mv "$SOURCE" "$TARGET"; then
  echo "Updater: failed to install new application directory" >&2
  rollback
  rm -rf "$STAGING"
  "$TARGET/$EXEC_NAME" >/dev/null 2>&1 &
  exit 21
fi

rm -rf "$STAGING"
rm -f "$ARCHIVE"
rmdir "$(dirname "$ARCHIVE")" 2>/dev/null || true
"$TARGET/$EXEC_NAME" >/dev/null 2>&1 &
sleep 2
rm -rf "$BACKUP"
rm -f "$0"
exit 0
'''


def spawn_windows_installer(installer: Path) -> None:
    if not installer.is_file():
        raise RuntimeError(f"Windows 更新安装包不存在: {installer}")
    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/SP-",
        ],
        cwd=str(installer.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )


def spawn_update_helper(archive: Path, target: Path) -> None:
    system = platform.system().lower()
    parent_pid = os.getpid()
    executable_name = Path(sys.executable).name
    log_path = _helper_log_path()

    if system == "darwin":
        script = _write_helper_script(".sh", _POSIX_MAC_HELPER)
        command = [
            "/bin/sh",
            str(script),
            str(archive),
            str(target),
            str(parent_pid),
        ]
        kwargs: dict[str, object] = {"start_new_session": True}
    elif system == "linux":
        script = _write_helper_script(".sh", _POSIX_LINUX_HELPER)
        command = [
            "/bin/sh",
            str(script),
            str(archive),
            str(target),
            str(parent_pid),
            executable_name,
        ]
        kwargs = {"start_new_session": True}
    else:
        raise RuntimeError(f"当前系统暂不支持自动更新: {platform.system()}")

    with log_path.open("ab") as log:
        subprocess.Popen(
            command,
            cwd=str(Path(tempfile.gettempdir())),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **kwargs,
        )


# Compatibility aliases kept private to avoid duplicating implementation.
_download_checksum = download_checksum
_spawn_windows_installer = spawn_windows_installer
_spawn_update_helper = spawn_update_helper


__all__ = [
    "MAX_CHECKSUM_BYTES",
    "UPDATE_DOWNLOAD_ATTEMPTS",
    "UPDATE_TIMEOUT_SECONDS",
    "current_install_target",
    "download_checksum",
    "sha256_file",
    "spawn_update_helper",
    "spawn_windows_installer",
]
