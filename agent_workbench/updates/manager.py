from __future__ import annotations

import http.client
import os
import platform
import shutil
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.resources import is_frozen
from .installer import (
    UPDATE_DOWNLOAD_ATTEMPTS,
    UPDATE_TIMEOUT_SECONDS,
    current_install_target,
    download_checksum,
    sha256_file,
    spawn_update_helper,
    spawn_windows_installer,
)
from .release import ReleaseInfo, _github_ssl_context


UPDATE_CHUNK_SIZE = 256 * 1024


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    state: str = "idle"
    version: str = ""
    progress: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "version": self.version,
            "progress": self.progress,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "message": self.message,
        }


class UpdateManager:
    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self._log = log or (lambda _message: None)
        self._lock = threading.RLock()
        self._status = UpdateStatus()
        self._release: ReleaseInfo | None = None
        self._archive: Path | None = None
        self._temp_dir: Path | None = None

    def status(self) -> UpdateStatus:
        with self._lock:
            return self._status

    def _set_status(self, **changes: object) -> None:
        with self._lock:
            current = self._status
            values = current.to_dict()
            values.update(changes)
            self._status = UpdateStatus(
                state=str(values["state"]),
                version=str(values["version"]),
                progress=int(values["progress"]),
                downloaded_bytes=int(values["downloaded_bytes"]),
                total_bytes=int(values["total_bytes"]),
                message=str(values["message"]),
            )

    def start(self, release: ReleaseInfo) -> UpdateStatus:
        if not is_frozen():
            raise RuntimeError("应用内更新只支持已打包安装的桌面程序。")
        if not release.update_available:
            raise RuntimeError("当前已经是最新版本。")
        if not release.update_download_url:
            raise RuntimeError(
                f"GitHub Release 缺少当前平台自动更新包: {release.update_asset_name}"
            )
        if not release.checksum_url:
            raise RuntimeError(
                f"GitHub Release 缺少校验文件: {release.update_asset_name}.sha256"
            )

        with self._lock:
            if self._status.state in {"downloading", "verifying", "installing"}:
                raise RuntimeError("更新任务正在进行中。")
            self._cleanup_download_locked()
            self._release = release
            self._status = UpdateStatus(
                state="downloading",
                version=release.latest_version,
                message="正在准备下载更新…",
            )

        threading.Thread(target=self._download_worker, daemon=True).start()
        return self.status()

    def _download_worker(self) -> None:
        release = self._release
        if release is None:
            return
        try:
            expected_sha256 = download_checksum(
                release.checksum_url,
                release.update_asset_name,
            )
            temp_dir = Path(
                tempfile.mkdtemp(prefix="micromatrix-workbench-update-download-")
            )
            archive = temp_dir / release.update_asset_name
            self._temp_dir = temp_dir
            self._download_archive(release.update_download_url, archive)
            self._set_status(
                state="verifying",
                progress=100,
                message="正在验证更新包…",
            )
            actual_sha256 = sha256_file(archive)
            if actual_sha256 != expected_sha256:
                raise RuntimeError("更新包 SHA-256 校验失败，已取消安装。")
            with self._lock:
                self._archive = archive
            self._set_status(
                state="ready",
                progress=100,
                message="下载完成，准备安装并重启…",
            )
            self._log(f"更新 {release.latest_version} 下载并校验完成。")
        except Exception as exc:
            self._log(f"自动更新下载失败: {exc}")
            self._set_status(state="error", message=str(exc))

    def _download_archive(self, url: str, destination: Path) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, UPDATE_DOWNLOAD_ATTEMPTS + 1):
            downloaded = 0
            total = 0
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/octet-stream",
                        "User-Agent": "MicroMatrix-Workbench-Updater",
                        "Connection": "close",
                    },
                )
                with urllib.request.urlopen(
                    request,
                    timeout=UPDATE_TIMEOUT_SECONDS,
                    context=_github_ssl_context(),
                ) as response, destination.open("wb") as output:
                    raw_length = response.headers.get("Content-Length")
                    if raw_length:
                        try:
                            total = max(0, int(raw_length))
                        except ValueError:
                            total = 0
                    while True:
                        chunk = response.read(UPDATE_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        progress = (
                            min(99, int(downloaded * 100 / total))
                            if total
                            else 0
                        )
                        self._set_status(
                            state="downloading",
                            progress=progress,
                            downloaded_bytes=downloaded,
                            total_bytes=total,
                            message="正在下载更新…",
                        )
                if total and downloaded != total:
                    raise http.client.IncompleteRead(b"", total - downloaded)
                self._set_status(
                    progress=99,
                    downloaded_bytes=downloaded,
                    total_bytes=total or downloaded,
                )
                return
            except urllib.error.HTTPError:
                destination.unlink(missing_ok=True)
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
                destination.unlink(missing_ok=True)
                if attempt >= UPDATE_DOWNLOAD_ATTEMPTS:
                    break
                self._set_status(
                    message=(
                        f"下载中断，正在重试 {attempt + 1}/{UPDATE_DOWNLOAD_ATTEMPTS}…"
                    )
                )
                time.sleep(0.5 * attempt)
        raise RuntimeError("更新包下载失败，请检查网络后重试。") from last_error

    def install_and_restart(self) -> UpdateStatus:
        with self._lock:
            if self._status.state != "ready" or self._archive is None:
                raise RuntimeError("更新包尚未准备完成。")
            archive = self._archive
            version = self._status.version
        try:
            if platform.system().lower() == "windows":
                spawn_windows_installer(archive)
                target = (
                    Path(os.environ.get("LOCALAPPDATA", ""))
                    / "Programs"
                    / "MicroMatrix"
                    / "MicroMatrix Workbench"
                )
            else:
                target = current_install_target()
                if not os.access(target.parent, os.W_OK):
                    raise RuntimeError(
                        f"没有权限替换当前安装目录: {target.parent}。"
                        "请将程序安装到当前用户可写的位置。"
                    )
                spawn_update_helper(archive, target)
        except Exception as exc:
            self._set_status(state="error", message=str(exc))
            raise
        self._set_status(
            state="installing",
            progress=100,
            message="正在退出程序，更新完成后会自动重新启动…",
        )
        self._log(f"已启动更新助手，将安装 {version} 到 {target}")
        return self.status()

    def _cleanup_download_locked(self) -> None:
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = None
        self._archive = None

    def cleanup(self) -> None:
        with self._lock:
            if self._status.state == "installing":
                # The detached helper owns the archive after install starts.
                return
            self._cleanup_download_locked()


__all__ = ["UPDATE_CHUNK_SIZE", "UpdateManager", "UpdateStatus"]
