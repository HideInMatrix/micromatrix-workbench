from __future__ import annotations

import threading
import time
from typing import Any

from ..core.settings import load_settings, save_settings
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
        settings = load_settings()
        settings[UPDATE_DOWNLOAD_PROXY_SETTING] = normalized
        save_settings(settings)
        self._latest_release = None
        return normalized

    def get_update_download_proxy(self) -> str:
        return self._update_download_proxy_prefix()

    def check_update(self) -> dict[str, object]:
        info = fetch_latest_release(
            self._app_version,
            download_proxy_prefix=self._update_download_proxy_prefix(),
        )
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

    def install_update(self) -> dict[str, object]:
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
