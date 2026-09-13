from __future__ import annotations

from pathlib import Path

from agent_runtime.toolchains.registration import normalize_registrations

from ..core.config import DEFAULT_HOST, LaunchConfig, NetworkConfig, default_lifecycle
from ..servers.models import MCPServerProfile


SENSITIVE_NETWORK_OPTIONS = {"tunnel_token", "authtoken"}


class ServiceAPI:
    """Work payload conversion, CRUD and lifecycle APIs."""

    @staticmethod
    def _runtime_payload_matches_profile(
        profile: MCPServerProfile,
        runtime_payload: dict[str, object],
        runtime_network: NetworkConfig,
    ) -> bool:
        try:
            workspace = Path(str(runtime_payload.get("workspace") or "")).expanduser()
            host = str(runtime_payload.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST
            port = int(runtime_payload.get("port") or 0)
            permission_mode = str(runtime_payload.get("permission_mode") or "").strip().lower()
            toolchains = normalize_registrations(
                runtime_payload.get("toolchains", profile.toolchains)
            )
        except (TypeError, ValueError):
            return False
        return bool(
            workspace == profile.workspace.expanduser()
            and host == profile.host
            and port == profile.port
            and permission_mode == profile.permission_mode
            and bool(runtime_payload.get("allow_network", False)) == profile.allow_network
            and bool(runtime_payload.get("enable_view_image", True)) == profile.enable_view_image
            and toolchains == profile.toolchains
            and runtime_network.provider == profile.network.provider
            and runtime_network.public_url == profile.network.public_url
        )

    def _network_from_payload(self, raw: object) -> NetworkConfig:
        value = raw if isinstance(raw, dict) else {}
        raw_options = value.get("options")
        options = raw_options if isinstance(raw_options, dict) else {}
        return NetworkConfig(
            provider=str(value.get("provider") or "cloudflare"),
            public_url=str(value.get("public_url") or ""),
            options={str(key): str(option) for key, option in options.items()},
        ).validated()

    def _persistable_network(
        self,
        network: NetworkConfig,
        remember: bool,
    ) -> NetworkConfig:
        options = dict(network.options)
        if not remember:
            for key in SENSITIVE_NETWORK_OPTIONS:
                options.pop(key, None)
        return NetworkConfig(
            provider=network.provider,
            public_url=network.public_url,
            options=options,
        ).validated()

    def _profile_payload(self, profile: MCPServerProfile) -> dict[str, object]:
        status = self.manager.status(profile.server_id)
        info = status.info
        return {
            "server_id": profile.server_id,
            "name": profile.name,
            "workspace": str(profile.workspace),
            "oauth_password": profile.oauth_password,
            "has_saved_password": bool(profile.oauth_password),
            "host": profile.host,
            "port": profile.port,
            "lifecycle": profile.lifecycle,
            "enabled": profile.enabled,
            "permission_mode": profile.permission_mode,
            "allow_network": profile.allow_network,
            "enable_view_image": profile.enable_view_image,
            "toolchains": list(profile.toolchains),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
            "network": {
                "provider": profile.network.provider,
                "public_url": profile.network.public_url,
                "options": dict(profile.network.options),
            },
            "running": status.running,
            "public_mcp_url": info.public_mcp_url if info else "",
            "url_mode": info.url_mode if info else "",
            "exit_reason": status.exit_reason,
        }

    def _next_available_port(self, start: int = 8234) -> int:
        used = {profile.port for profile in self.store.list()}
        for port in range(max(1, int(start)), 65536):
            if port not in used:
                return port
        raise RuntimeError("没有可用的 TCP 端口可分配。")

    def list_servers(self) -> list[dict[str, object]]:
        return [self._profile_payload(profile) for profile in self.store.list()]

    def get_next_port(self) -> int:
        return self._next_available_port()

    def select_server(self, server_id: str) -> bool:
        if self.store.get(server_id) is None:
            return False
        self._save_selected_server_id(server_id)
        return True

    def create_server(self, payload: dict[str, object]) -> dict[str, object]:
        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        profile = self.store.create(
            name=str(payload.get("name") or ""),
            workspace=Path(str(payload.get("workspace") or "")),
            oauth_password=(str(payload.get("oauth_password") or "") if remember else ""),
            network=self._persistable_network(network, remember),
            host=str(payload.get("host") or "127.0.0.1"),
            port=int(payload.get("port") or self._next_available_port()),
            lifecycle=default_lifecycle(network),
            enabled=bool(payload.get("enabled", False)),
            permission_mode=str(payload.get("permission_mode") or "safe"),
            allow_network=bool(payload.get("allow_network", False)),
            enable_view_image=bool(payload.get("enable_view_image", True)),
            toolchains=tuple(payload.get("toolchains", [])),
        )
        self._save_selected_server_id(profile.server_id)
        return self._profile_payload(profile)

    def update_server(self, server_id: str, payload: dict[str, object]) -> dict[str, object]:
        current = self.store.get(server_id)
        if current is None:
            raise KeyError(f"找不到 Work: {server_id}")
        if self.manager.is_running(server_id):
            raise RuntimeError("请先停止当前 Work，再修改配置。")
        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        profile = self.store.save(
            MCPServerProfile(
                server_id=current.server_id,
                name=str(payload.get("name") or current.name),
                workspace=Path(str(payload.get("workspace") or current.workspace)),
                oauth_password=(str(payload.get("oauth_password") or "") if remember else ""),
                network=self._persistable_network(network, remember),
                host=str(payload.get("host") or current.host),
                port=int(payload.get("port") or current.port),
                lifecycle=default_lifecycle(network),
                enabled=bool(payload.get("enabled", current.enabled)),
                permission_mode=str(payload.get("permission_mode") or current.permission_mode),
                allow_network=bool(payload.get("allow_network", current.allow_network)),
                enable_view_image=bool(payload.get("enable_view_image", current.enable_view_image)),
                toolchains=tuple(payload.get("toolchains", current.toolchains)),
                created_at=current.created_at,
                updated_at=current.updated_at,
            )
        )
        return self._profile_payload(profile)

    def delete_server(self, server_id: str) -> bool:
        deleted = self.manager.delete_profile(server_id)
        if deleted:
            self.permission_broker.clear_server(server_id)
        if deleted and self._selected_server_id() == server_id:
            profiles = self.store.list()
            self._save_selected_server_id(profiles[0].server_id if profiles else "")
        return deleted

    def start_server(
        self,
        server_id: str,
        runtime_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        profile = self.store.get(server_id)
        if profile is None:
            raise KeyError(f"找不到 Work: {server_id}")
        if runtime_payload:
            raw_network = runtime_payload.get("network")
            network_payload = raw_network if isinstance(raw_network, dict) else {}
            runtime_network = self._network_from_payload(network_payload)
            if not self._runtime_payload_matches_profile(
                profile,
                runtime_payload,
                runtime_network,
            ):
                raise ValueError("运行配置与已保存 Work 不一致，请先保存配置。")
            merged_options = dict(profile.network.options)
            for key, value in runtime_network.options.items():
                if value:
                    merged_options[key] = value
            network = NetworkConfig(
                provider=profile.network.provider,
                public_url=profile.network.public_url,
                options=merged_options,
            ).validated()
            config = LaunchConfig(
                workspace=profile.workspace,
                oauth_password=str(runtime_payload.get("oauth_password") or profile.oauth_password),
                network=network,
                host=profile.host,
                port=profile.port,
                server_id=profile.server_id,
                lifecycle=profile.lifecycle,
                permission_mode=profile.permission_mode,
                allow_network=profile.allow_network,
                enable_view_image=profile.enable_view_image,
                toolchains=profile.toolchains,
            ).validated()
            self.manager.start_config(server_id, config)
        else:
            self.manager.start(server_id)
        return self._profile_payload(self.store.get(server_id) or profile)

    def stop_server(self, server_id: str) -> dict[str, object]:
        self.manager.stop(server_id)
        self.permission_broker.clear_server(server_id)
        profile = self.store.get(server_id)
        if profile is None:
            raise KeyError(f"找不到 Work: {server_id}")
        return self._profile_payload(profile)

    def set_server_enabled(self, server_id: str, enabled: bool) -> dict[str, object]:
        current = self.store.get(server_id)
        if current is None:
            raise KeyError(f"找不到 Work: {server_id}")
        desired = bool(enabled)
        updated = self.store.save(
            MCPServerProfile(
                server_id=current.server_id,
                name=current.name,
                workspace=current.workspace,
                oauth_password=current.oauth_password,
                network=current.network,
                host=current.host,
                port=current.port,
                lifecycle=current.lifecycle,
                enabled=desired,
                permission_mode=current.permission_mode,
                allow_network=current.allow_network,
                enable_view_image=current.enable_view_image,
                toolchains=current.toolchains,
                created_at=current.created_at,
                updated_at=current.updated_at,
            )
        )
        return self._profile_payload(self.store.get(server_id) or updated)


__all__ = ["SENSITIVE_NETWORK_OPTIONS", "ServiceAPI"]
