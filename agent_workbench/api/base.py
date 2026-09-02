from __future__ import annotations

import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Protocol

from ..core.settings import load_settings, save_settings, settings_dir
from ..core.version import current_version
from ..executables import resolve_executable
from ..gateways.manager import MCPGatewayManager
from ..gateways.store import GatewayProfileStore
from ..network.specs import network_provider_catalog
from ..runtime.permission_broker import DesktopPermissionBroker
from ..servers.manager import MCPServerManager
from ..servers.store import ServerProfileStore
from ..updates.manager import UpdateManager
from .workbench_manager import DesktopWorkbenchManager


class DesktopAPIContext(Protocol):
    store: ServerProfileStore
    gateway_store: GatewayProfileStore
    permission_broker: DesktopPermissionBroker
    manager: MCPServerManager
    gateway_manager: MCPGatewayManager
    workbench_manager: DesktopWorkbenchManager
    update_manager: UpdateManager
    _app_version: str
    _window: Any | None
    _latest_release: Any | None


class DesktopBaseAPI:
    """Shared desktop bridge state, lifecycle, settings, logs and OS helpers."""

    def __init__(self, *, app_version: str | None = None) -> None:
        self._app_version = app_version or current_version()
        self.store = ServerProfileStore()
        self.gateway_store = GatewayProfileStore()
        self.permission_broker = DesktopPermissionBroker()
        self._log_lock = threading.RLock()
        self._log_cursor = 0
        self._logs: deque[dict[str, object]] = deque(maxlen=2000)
        self.manager = MCPServerManager(
            store=self.store,
            log=self._append_log,
            permission_broker=self.permission_broker,
        )
        self.gateway_manager = MCPGatewayManager(
            store=self.gateway_store,
            log=self._append_log,
            permission_broker=self.permission_broker,
        )
        self.workbench_manager = DesktopWorkbenchManager(
            server_store=self.store,
            gateway_store=self.gateway_store,
            server_manager=self.manager,
            gateway_manager=self.gateway_manager,
            global_root=settings_dir() / "workbench",
        )
        self.update_manager = UpdateManager(log=self._append_log)
        self._latest_release = None
        self._window: Any | None = None
        self._permission_attention_id = ""
        self._workflow_approval_attention_id = ""

    def _bind_window(self, window: Any) -> None:
        self._window = window

    def _close(self) -> None:
        self.manager.stop_all()
        self.gateway_manager.stop_all()
        self.update_manager.cleanup()
        self.permission_broker.cleanup()

    def _append_log(self, message: str) -> None:
        with self._log_lock:
            self._log_cursor += 1
            self._logs.append(
                {
                    "id": self._log_cursor,
                    "time": int(time.time()),
                    "message": str(message),
                }
            )

    def _selected_server_id(self) -> str:
        return str(load_settings().get("selected_server_id") or "")

    def _save_selected_server_id(self, server_id: str) -> None:
        settings = load_settings()
        settings["selected_server_id"] = server_id
        save_settings(settings)

    def bootstrap(self) -> dict[str, object]:
        profiles = self.store.list()
        gateways = self.gateway_store.list()
        selected = self._selected_server_id()
        ids = {profile.server_id for profile in profiles}
        if selected not in ids:
            selected = profiles[0].server_id if profiles else ""
        return {
            "app_name": "MicroMatrix Workbench",
            "version": self._app_version,
            "update_download_proxy_prefix": self._update_download_proxy_prefix(),
            "selected_server_id": selected,
            "next_default_port": self._next_available_port(),
            "servers": [self._profile_payload(profile) for profile in profiles],
            "gateways": [self._gateway_payload(gateway) for gateway in gateways],
            "network_providers": network_provider_catalog(),
        }

    def list_network_providers(self) -> list[dict[str, object]]:
        return network_provider_catalog()

    def get_app_version(self) -> str:
        return self._app_version

    def get_selected_server_id(self) -> str:
        profiles = self.store.list()
        selected = self._selected_server_id()
        ids = {profile.server_id for profile in profiles}
        if selected in ids:
            return selected
        return profiles[0].server_id if profiles else ""

    def get_logs(self, after: int = 0) -> dict[str, object]:
        with self._log_lock:
            entries = [
                entry for entry in self._logs if int(entry["id"]) > int(after)
            ]
            return {"cursor": self._log_cursor, "entries": entries}

    def clear_logs(self) -> int:
        with self._log_lock:
            self._logs.clear()
            return self._log_cursor

    def detect_executable(
        self,
        product: str,
        configured: str = "",
    ) -> dict[str, object]:
        candidate = resolve_executable(product, configured=configured, auto_only=True)
        return {
            "path": str(candidate.path),
            "source": candidate.source,
            "version": candidate.version,
        }

    def choose_workspace(self, initial: str = "") -> str:
        if self._window is None:
            return ""
        import webview

        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=initial or str(Path.home()),
        )
        return str(result[0]) if result else ""

    def choose_file(self, initial: str = "") -> str:
        if self._window is None:
            return ""
        import webview

        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=initial or str(Path.home()),
        )
        return str(result[0]) if result else ""

    def open_external(self, url: str) -> bool:
        value = url.strip()
        if not value.startswith(("https://", "http://")):
            raise ValueError("只允许打开 http/https 地址。")
        return bool(webbrowser.open(value))


__all__ = ["DesktopAPIContext", "DesktopBaseAPI"]
