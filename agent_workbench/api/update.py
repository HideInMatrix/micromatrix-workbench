from __future__ import annotations

import threading
import time
from typing import Any

from ..core.settings import load_settings, save_settings
from ..updates.cache import CHECK_INTERVAL_SECONDS
from ..updates.release import (
    DEFAULT_GITHUB_DOWNLOAD_PROXY,
    fetch_latest_release,
    normalize_download_proxy_prefix,
)


UPDATE_DOWNLOAD_PROXY_SETTING = "update_download_proxy_prefix"


class UpdateAPI:
    """Release checking, updater state and install bridge methods."""

    @staticmethod
    def _release_payload(info: Any) -> dict[str, object]:
        return {
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "tag_name": info.tag_name,
            "release_url": info.release_url,
            "asset_name": info.asset_name,
            "download_url": info.download_url,
            "update_asset_name": info.update_asset_name,
            "update_download_url": info.update_download_url,
            "checksum_url": info.checksum_url,
            "update_available": info.update_available,
        }

    def _update_download_proxy_prefix(self) -> str:
        settings = load_settings()
        raw = settings.get(
            UPDATE_DOWNLOAD_PROXY_SETTING,
            DEFAULT_GITHUB_DOWNLOAD_PROXY,
        )
        try:
            return normalize_download_proxy_prefix(raw)
        except ValueError:
            return DEFAULT_GITHUB_DOWNLOAD_PROXY

    def save_update_download_proxy(self, prefix: str) -> str:
        normalized = normalize_download_proxy_prefix(prefix)
        with self._update_check_lock:
            settings = load_settings()
            settings[UPDATE_DOWNLOAD_PROXY_SETTING] = normalized
            save_settings(settings)
            self._latest_release = None
        return normalized

    def get_update_download_proxy(self) -> str:
        return self._update_download_proxy_prefix()

    def get_update_check_state(self) -> dict[str, object]:
        with self._update_check_lock:
            info, checked = self._update_check_cache.read(
                self._app_version, self._update_download_proxy_prefix(), time.time(),
            )
            return {"release": self._release_payload(info) if info else None,
                    "last_checked_at": checked}

    def check_update(self, force: bool = True) -> dict[str, object]:
        with self._update_check_lock:
            proxy = self._update_download_proxy_prefix()
            info, checked = self._update_check_cache.read(self._app_version, proxy, time.time())
            if force or info is None or time.time() - checked >= CHECK_INTERVAL_SECONDS:
                info = fetch_latest_release(self._app_version, download_proxy_prefix=proxy)
                try:
                    self._update_check_cache.write(info, proxy, time.time())
                except OSError as exc:
                    self._append_log(f"更新检查成功，但缓存写入失败: {exc}")
            self._latest_release = info
            return self._release_payload(info)

    def start_update(self) -> dict[str, object]:
        info = self._latest_release
        if info is None:
            info = fetch_latest_release(
                self._app_version,
                download_proxy_prefix=self._update_download_proxy_prefix(),
            )
            self._latest_release = info
        return self.update_manager.start(info).to_dict()

    def update_status(self) -> dict[str, object]:
        return self.update_manager.status().to_dict()

    def get_update_install_impact(self) -> dict[str, object]:
        services = [
            {"id": f"work:{item.server_id}", "name": item.name}
            for item in self.manager.statuses()
            if item.running
        ]
        return {"version": self.update_manager.status().version, "services": services}

    def install_update(self, confirmed_services: list[str] | None = None) -> dict[str, object]:
        impact = self.get_update_install_impact()
        active = {item["id"] for item in impact["services"]}
        if active != set(confirmed_services or []):
            raise RuntimeError("运行中的服务已变化，请重新确认将停止的服务后安装。")
        status = self.update_manager.install_and_restart()
        threading.Thread(
            target=self._close_window_for_update,
            daemon=True,
        ).start()
        return status.to_dict()

    def _close_window_for_update(self) -> None:
        time.sleep(0.35)
        window = self._window
        if window is not None:
            window.destroy()


__all__ = ["UPDATE_DOWNLOAD_PROXY_SETTING", "UpdateAPI"]
