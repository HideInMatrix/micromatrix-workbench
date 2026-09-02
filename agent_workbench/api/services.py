from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..core.config import LaunchConfig, NetworkConfig, default_lifecycle
from ..gateways.models import MCPGatewayMember, MCPGatewayProfile
from ..oauth.persistence import (
    bound_server_oauth_issuer,
    delete_issuer_oauth_storage,
    delete_server_oauth_storage,
)
from ..servers.models import MCPServerProfile


SENSITIVE_NETWORK_OPTIONS = {"tunnel_token", "authtoken"}


class ServiceAPI:
    """Server/Gateway payload conversion, CRUD and lifecycle APIs."""

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
        try:
            oauth_client_count = len(self.manager.oauth_clients(profile.server_id))
        except Exception:
            oauth_client_count = 0
        return {
            "server_id": profile.server_id,
            "name": profile.name,
            "workspace": str(profile.workspace),
            "oauth_password": profile.oauth_password,
            "has_saved_password": bool(profile.oauth_password),
            "host": profile.host,
            "port": profile.port,
            "lifecycle": profile.lifecycle,
            "permission_mode": profile.permission_mode,
            "allow_network": profile.allow_network,
            "enable_view_image": profile.enable_view_image,
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
            "oauth_client_count": oauth_client_count,
        }

    @staticmethod
    def _public_hostname(network: NetworkConfig) -> str:
        if not network.public_url:
            return ""
        return (urlsplit(network.public_url).hostname or "").lower()

    @staticmethod
    def _member_public_hostname(member: MCPGatewayMember) -> str:
        if not member.public_url:
            return ""
        return (urlsplit(member.public_url).hostname or "").lower()

    def _gateway_public_hostnames(self, gateway: MCPGatewayProfile) -> set[str]:
        return {
            hostname
            for hostname in (
                self._public_hostname(gateway.network),
                *(
                    self._member_public_hostname(member)
                    for member in gateway.members
                ),
            )
            if hostname
        }

    def _next_available_port(self, start: int = 8234) -> int:
        used = {profile.port for profile in self.store.list()}
        used.update(gateway.port for gateway in self.gateway_store.list())
        for port in range(max(1, int(start)), 65536):
            if port not in used:
                return port
        raise RuntimeError("没有可用的 TCP 端口可分配。")

    def _assert_direct_resources_available(
        self,
        *,
        network: NetworkConfig,
        host: str,
        port: int,
    ) -> None:
        hostname = self._public_hostname(network)
        for gateway in self.gateway_store.list():
            if gateway.host == host and gateway.port == port:
                raise ValueError(
                    f"该地址已被 Local MCP Gateway 使用: {host}:{port}"
                )
            if hostname and hostname in self._gateway_public_hostnames(gateway):
                raise ValueError(
                    "该 Public Hostname 已被 Local MCP Gateway 使用；"
                    "直连 Server 必须使用独立 hostname。"
                )

    def _assert_gateway_resources_available(
        self,
        *,
        network: NetworkConfig,
        host: str,
        port: int,
        members: tuple[MCPGatewayMember, ...] = (),
        ignore_server_id: str = "",
    ) -> None:
        hostnames = {
            hostname
            for hostname in (
                self._public_hostname(network),
                *(
                    self._member_public_hostname(member)
                    for member in members
                ),
            )
            if hostname
        }
        for profile in self.store.list():
            if ignore_server_id and profile.server_id == ignore_server_id:
                continue
            if profile.host == host and profile.port == port:
                raise ValueError(
                    f"该地址已被直连 MCP Server 使用: {host}:{port}"
                )
            if self._public_hostname(profile.network) in hostnames:
                raise ValueError(
                    "该 Public Hostname 已被直连 MCP Server 使用；"
                    "Gateway 必须使用独立 hostname。"
                )

    @staticmethod
    def _validate_gateway_hostname_model(
        network: NetworkConfig,
        members: tuple[MCPGatewayMember, ...],
        mode: str,
    ) -> None:
        if mode != "multi":
            return
        if not network.public_url:
            raise ValueError(
                "多 Workspace 模式需要固定 Public Hostname；"
                "Cloudflare 请使用 Named Tunnel。"
            )
        missing = [member.name for member in members if not member.public_url]
        if missing:
            raise ValueError(
                "多 Workspace 模式要求每个 Profile 配置独立 Public Hostname。"
                f"缺少: {', '.join(missing)}"
            )
        primary = members[0].public_url.rstrip("/")
        if primary != network.public_url.rstrip("/"):
            raise ValueError(
                "主 Workspace Profile Hostname 必须与服务 Public Hostname 一致。"
            )

    def _gateway_payload(self, gateway: MCPGatewayProfile) -> dict[str, object]:
        status = self.gateway_manager.status(gateway.gateway_id)
        info = status.info
        members: list[dict[str, object]] = []
        for member in gateway.members:
            runtime_info = info.profile(member.server_id) if info else None
            try:
                oauth_client_count = len(
                    self.gateway_manager.oauth_clients(
                        gateway.gateway_id,
                        member.server_id,
                    )
                )
            except Exception:
                oauth_client_count = 0
            members.append(
                {
                    "server_id": member.server_id,
                    "name": member.name,
                    "workspace": str(member.workspace),
                    "oauth_password": member.oauth_password,
                    "has_saved_password": bool(member.oauth_password),
                    "instance_path": member.instance_path,
                    "public_url": member.public_url,
                    "permission_mode": member.permission_mode,
                    "lifecycle": member.lifecycle,
                    "allow_network": member.allow_network,
                    "enable_view_image": member.enable_view_image,
                    "public_mcp_url": (
                        runtime_info.public_mcp_url if runtime_info else ""
                    ),
                    "local_mcp_url": (
                        runtime_info.local_mcp_url if runtime_info else ""
                    ),
                    "oauth_issuer": (
                        runtime_info.oauth_issuer if runtime_info else ""
                    ),
                    "oauth_client_count": oauth_client_count,
                }
            )
        return {
            "gateway_id": gateway.gateway_id,
            "name": gateway.name,
            "mode": gateway.mode,
            "host": gateway.host,
            "port": gateway.port,
            "created_at": gateway.created_at,
            "updated_at": gateway.updated_at,
            "network": {
                "provider": gateway.network.provider,
                "public_url": gateway.network.public_url,
                "options": dict(gateway.network.options),
            },
            "members": members,
            "running": status.running,
            "public_base_url": info.public_base_url if info else "",
            "url_mode": info.url_mode if info else "",
            "exit_reason": status.exit_reason,
            "diagnostic": (
                self._gateway_diagnostic_payload(status.diagnostic)
                if status.diagnostic is not None
                else None
            ),
        }

    @staticmethod
    def _gateway_diagnostic_payload(report: Any) -> dict[str, object]:
        return {
            "ok": bool(report.ok),
            "public_base_url": str(report.public_base_url),
            "checked_at": int(report.checked_at),
            "profiles": [
                {
                    "server_id": profile.server_id,
                    "name": profile.name,
                    "instance_path": profile.instance_path,
                    "public_base_url": profile.public_base_url,
                    "ok": profile.ok,
                    "checks": list(profile.checks),
                    "errors": list(profile.errors),
                }
                for profile in report.profiles
            ],
        }

    def _gateway_member_from_payload(
        self,
        raw: object,
        *,
        lifecycle: str,
        remember_secrets: bool,
        current: MCPGatewayMember | None = None,
    ) -> MCPGatewayMember:
        value = raw if isinstance(raw, dict) else {}
        server_id = str(
            value.get("server_id") or (current.server_id if current else "")
        )
        password = (
            str(
                value.get("oauth_password")
                or (current.oauth_password if current else "")
            )
            if remember_secrets
            else ""
        )
        if server_id:
            return MCPGatewayMember(
                server_id=server_id,
                name=str(value.get("name") or (current.name if current else "")),
                workspace=Path(
                    str(
                        value.get("workspace")
                        or (current.workspace if current else "")
                    )
                ),
                oauth_password=password,
                instance_path=str(
                    value.get("instance_path")
                    or (current.instance_path if current else "")
                ),
                public_url=str(
                    value.get("public_url")
                    or (current.public_url if current else "")
                ),
                permission_mode=str(
                    value.get("permission_mode")
                    or (current.permission_mode if current else "safe")
                ),
                lifecycle=lifecycle,
                allow_network=bool(
                    value.get(
                        "allow_network",
                        current.allow_network if current else False,
                    )
                ),
                enable_view_image=bool(
                    value.get(
                        "enable_view_image",
                        current.enable_view_image if current else True,
                    )
                ),
            ).validated()
        return MCPGatewayMember.create(
            name=str(value.get("name") or ""),
            workspace=Path(str(value.get("workspace") or "")),
            oauth_password=password,
            instance_path=str(value.get("instance_path") or ""),
            public_url=str(value.get("public_url") or ""),
            permission_mode=str(value.get("permission_mode") or "safe"),
            lifecycle=lifecycle,
            allow_network=bool(value.get("allow_network", False)),
            enable_view_image=bool(value.get("enable_view_image", True)),
        )

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
        host = str(payload.get("host") or "127.0.0.1")
        port = int(payload.get("port") or self._next_available_port())
        self._assert_direct_resources_available(
            network=network,
            host=host,
            port=port,
        )
        profile = self.store.create(
            name=str(payload.get("name") or ""),
            workspace=Path(str(payload.get("workspace") or "")),
            oauth_password=(
                str(payload.get("oauth_password") or "") if remember else ""
            ),
            network=self._persistable_network(network, remember),
            host=host,
            port=port,
            lifecycle=default_lifecycle(network),
            permission_mode=str(payload.get("permission_mode") or "safe"),
            allow_network=bool(payload.get("allow_network", False)),
            enable_view_image=bool(payload.get("enable_view_image", True)),
        )
        self._save_selected_server_id(profile.server_id)
        return self._profile_payload(profile)

    def update_server(
        self,
        server_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        current = self.store.get(server_id)
        if current is None:
            raise KeyError(f"找不到 MCP Server: {server_id}")
        if self.manager.is_running(server_id):
            raise RuntimeError("请先停止当前 MCP Server，再修改配置。")

        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        host = str(payload.get("host") or current.host)
        port = int(payload.get("port") or current.port)
        self._assert_direct_resources_available(
            network=network,
            host=host,
            port=port,
        )
        profile = self.store.save(
            MCPServerProfile(
                server_id=current.server_id,
                name=str(payload.get("name") or current.name),
                workspace=Path(
                    str(payload.get("workspace") or current.workspace)
                ),
                oauth_password=(
                    str(payload.get("oauth_password") or "") if remember else ""
                ),
                network=self._persistable_network(network, remember),
                host=host,
                port=port,
                lifecycle=default_lifecycle(network),
                permission_mode=str(
                    payload.get("permission_mode") or current.permission_mode
                ),
                allow_network=bool(
                    payload.get("allow_network", current.allow_network)
                ),
                enable_view_image=bool(
                    payload.get("enable_view_image", current.enable_view_image)
                ),
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
            self._save_selected_server_id(
                profiles[0].server_id if profiles else ""
            )
        return deleted

    def start_server(
        self,
        server_id: str,
        runtime_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        profile = self.store.get(server_id)
        if profile is None:
            raise KeyError(f"找不到 MCP Server: {server_id}")

        if runtime_payload:
            raw_network = runtime_payload.get("network")
            network_payload = raw_network if isinstance(raw_network, dict) else {}
            runtime_network = self._network_from_payload(network_payload)
            if (
                runtime_network.provider != profile.network.provider
                or runtime_network.public_url != profile.network.public_url
            ):
                raise ValueError(
                    "运行配置与已保存 Server Profile 不一致，请先保存配置。"
                )
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
                oauth_password=str(
                    runtime_payload.get("oauth_password")
                    or profile.oauth_password
                ),
                network=network,
                host=profile.host,
                port=profile.port,
                server_id=profile.server_id,
                lifecycle=profile.lifecycle,
                permission_mode=profile.permission_mode,
                allow_network=profile.allow_network,
                enable_view_image=profile.enable_view_image,
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
            raise KeyError(f"找不到 MCP Server: {server_id}")
        return self._profile_payload(profile)

    def list_gateways(self) -> list[dict[str, object]]:
        return [
            self._gateway_payload(gateway)
            for gateway in self.gateway_store.list()
        ]

    def create_gateway(self, payload: dict[str, object]) -> dict[str, object]:
        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        host = str(payload.get("host") or "127.0.0.1")
        port = int(payload.get("port") or self._next_available_port())
        raw_members = payload.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("Gateway 至少需要一个 Member。")
        lifecycle = default_lifecycle(network)
        members = tuple(
            self._gateway_member_from_payload(
                raw,
                lifecycle=lifecycle,
                remember_secrets=remember,
            )
            for raw in raw_members
        )
        mode = str(payload.get("mode") or "multi").strip().lower()
        self._validate_gateway_hostname_model(network, members, mode)
        self._assert_gateway_resources_available(
            network=network,
            host=host,
            port=port,
            members=members,
        )
        gateway = self.gateway_store.create(
            name=str(payload.get("name") or ""),
            network=self._persistable_network(network, remember),
            members=members,
            mode=mode,
            host=host,
            port=port,
        )
        return self._gateway_payload(gateway)

    def _updated_gateway_members(
        self,
        current: MCPGatewayProfile,
        raw_members: object,
        *,
        lifecycle: str,
        remember_secrets: bool,
    ) -> tuple[tuple[MCPGatewayMember, ...], tuple[MCPGatewayMember, ...]]:
        current_by_id = {member.server_id: member for member in current.members}
        if raw_members is None:
            raw_members = [member.to_dict() for member in current.members]
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("Gateway 至少需要一个 Member。")
        members = tuple(
            self._gateway_member_from_payload(
                raw if isinstance(raw, dict) else {},
                lifecycle=lifecycle,
                remember_secrets=remember_secrets,
                current=current_by_id.get(
                    str(raw.get("server_id") or "")
                    if isinstance(raw, dict)
                    else ""
                ),
            )
            for raw in raw_members
        )
        member_ids = {member.server_id for member in members}
        removed = tuple(
            member
            for member in current.members
            if member.server_id not in member_ids
        )
        return members, removed

    def _cleanup_removed_gateway_members(
        self,
        removed_members: tuple[MCPGatewayMember, ...],
    ) -> None:
        issuers = {
            member.server_id: bound_server_oauth_issuer(member.server_id)
            for member in removed_members
        }
        for member in removed_members:
            self.permission_broker.clear_server(member.server_id)
            delete_server_oauth_storage(member.server_id)
            issuer = issuers.get(member.server_id)
            if issuer and not self._oauth_identity_still_referenced(issuer):
                delete_issuer_oauth_storage(issuer)

    def _promoted_gateway_members(
        self,
        current: MCPServerProfile,
        raw_members: object,
        *,
        lifecycle: str,
        remember_secrets: bool,
    ) -> tuple[MCPGatewayMember, ...]:
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("服务至少需要一个 Workspace Profile。")
        members: list[MCPGatewayMember] = []
        root_seen = False
        for raw in raw_members:
            value = raw if isinstance(raw, dict) else {}
            instance_path = str(value.get("instance_path") or "")
            if instance_path.strip().strip("/"):
                members.append(
                    self._gateway_member_from_payload(
                        value,
                        lifecycle=lifecycle,
                        remember_secrets=remember_secrets,
                    )
                )
                continue
            if root_seen:
                raise ValueError("一个服务只能有一个根 Workspace Profile。")
            root_seen = True
            members.append(
                MCPGatewayMember(
                    server_id=current.server_id,
                    name=str(value.get("name") or current.name),
                    workspace=Path(
                        str(value.get("workspace") or current.workspace)
                    ),
                    oauth_password=(
                        str(
                            value.get("oauth_password")
                            or current.oauth_password
                        )
                        if remember_secrets
                        else ""
                    ),
                    instance_path="",
                    public_url=str(
                        value.get("public_url") or current.network.public_url
                    ),
                    permission_mode=str(
                        value.get("permission_mode") or current.permission_mode
                    ),
                    lifecycle=lifecycle,
                    allow_network=bool(value.get("allow_network", False)),
                    enable_view_image=bool(value.get("enable_view_image", True)),
                ).validated()
            )
        if not root_seen:
            raise ValueError(
                "从单 Workspace 升级时必须保留原来的根 Workspace Profile。"
            )
        if len(members) < 2:
            raise ValueError("没有新增子 Profile，无需切换到多 Workspace Runtime。")
        return tuple(members)

    def update_gateway(
        self,
        gateway_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        current = self.gateway_store.get(gateway_id)
        if current is None:
            raise KeyError(f"找不到 Local MCP Gateway: {gateway_id}")
        if self.gateway_manager.is_running(gateway_id):
            raise RuntimeError("请先停止 Local MCP Gateway，再修改配置。")

        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        host = str(payload.get("host") or current.host)
        port = int(payload.get("port") or current.port)
        lifecycle = default_lifecycle(network)
        members, removed_members = self._updated_gateway_members(
            current,
            payload.get("members"),
            lifecycle=lifecycle,
            remember_secrets=remember,
        )
        mode = str(payload.get("mode") or current.mode).strip().lower()
        self._validate_gateway_hostname_model(network, members, mode)
        self._assert_gateway_resources_available(
            network=network,
            host=host,
            port=port,
            members=members,
        )
        gateway = self.gateway_store.save(
            MCPGatewayProfile(
                gateway_id=current.gateway_id,
                name=str(payload.get("name") or current.name),
                network=self._persistable_network(network, remember),
                members=members,
                mode=mode,
                host=host,
                port=port,
                created_at=current.created_at,
                updated_at=current.updated_at,
            )
        )
        self._cleanup_removed_gateway_members(removed_members)
        return self._gateway_payload(gateway)

    def promote_server_to_gateway(
        self,
        server_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        current = self.store.get(server_id)
        if current is None:
            raise KeyError(f"找不到 MCP Server: {server_id}")
        if self.manager.is_running(server_id):
            raise RuntimeError("请先停止当前服务，再添加子 Profile。")

        network = self._network_from_payload(payload.get("network"))
        remember = bool(payload.get("remember_secrets", True))
        host = str(payload.get("host") or current.host)
        port = int(payload.get("port") or current.port)
        lifecycle = default_lifecycle(network)
        members = self._promoted_gateway_members(
            current,
            payload.get("members"),
            lifecycle=lifecycle,
            remember_secrets=remember,
        )
        mode = str(payload.get("mode") or "multi").strip().lower()
        self._validate_gateway_hostname_model(network, members, mode)
        self._assert_gateway_resources_available(
            network=network,
            host=host,
            port=port,
            members=members,
            ignore_server_id=server_id,
        )

        gateway = self.gateway_store.save(
            MCPGatewayProfile(
                gateway_id=current.server_id,
                name=str(payload.get("name") or current.name),
                network=self._persistable_network(network, remember),
                members=members,
                mode=mode,
                host=host,
                port=port,
                created_at=current.created_at,
                updated_at=current.updated_at,
            )
        )
        if not self.store.delete(server_id):
            self.gateway_store.delete(gateway.gateway_id)
            raise RuntimeError(
                "服务运行模型转换失败：旧 Direct Profile 未能移除。"
            )
        return self._gateway_payload(gateway)

    def _oauth_identity_still_referenced(self, issuer: str) -> bool:
        for profile in self.store.list():
            if bound_server_oauth_issuer(profile.server_id) == issuer:
                return True
        for gateway in self.gateway_store.list():
            for member in gateway.members:
                if bound_server_oauth_issuer(member.server_id) == issuer:
                    return True
        return False

    def delete_gateway(self, gateway_id: str) -> bool:
        gateway = self.gateway_store.get(gateway_id)
        if gateway is None:
            return False
        issuers = {
            member.server_id: bound_server_oauth_issuer(member.server_id)
            for member in gateway.members
        }
        deleted = self.gateway_manager.delete_profile(gateway_id)
        if not deleted:
            return False
        for member in gateway.members:
            self.permission_broker.clear_server(member.server_id)
            delete_server_oauth_storage(member.server_id)
            issuer = issuers.get(member.server_id)
            if issuer and not self._oauth_identity_still_referenced(issuer):
                delete_issuer_oauth_storage(issuer)
        return True

    def start_gateway(
        self,
        gateway_id: str,
        runtime_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        gateway = self.gateway_store.get(gateway_id)
        if gateway is None:
            raise KeyError(f"找不到 Local MCP Gateway: {gateway_id}")

        if runtime_payload:
            raw_network = runtime_payload.get("network")
            network_payload = raw_network if isinstance(raw_network, dict) else {}
            runtime_network = self._network_from_payload(network_payload)
            merged_options = dict(gateway.network.options)
            for key, value in runtime_network.options.items():
                if value:
                    merged_options[key] = value
            network = NetworkConfig(
                provider=gateway.network.provider,
                public_url=gateway.network.public_url,
                options=merged_options,
            ).validated()
            raw_members = runtime_payload.get("members")
            oauth_passwords: dict[str, str] = {}
            if isinstance(raw_members, list):
                for raw in raw_members:
                    if not isinstance(raw, dict):
                        continue
                    server_id = str(raw.get("server_id") or "")
                    if server_id:
                        oauth_passwords[server_id] = str(
                            raw.get("oauth_password") or ""
                        )
            config = gateway.runtime_launch_config(
                network=network,
                oauth_passwords=oauth_passwords,
            )
            self.gateway_manager.start_config(gateway_id, config)
        else:
            self.gateway_manager.start(gateway_id)
        return self._gateway_payload(
            self.gateway_store.get(gateway_id) or gateway
        )

    def stop_gateway(self, gateway_id: str) -> dict[str, object]:
        self.gateway_manager.stop(gateway_id)
        gateway = self.gateway_store.get(gateway_id)
        if gateway is None:
            raise KeyError(f"找不到 Local MCP Gateway: {gateway_id}")
        for member in gateway.members:
            self.permission_broker.clear_server(member.server_id)
        return self._gateway_payload(gateway)

    def test_gateway(self, gateway_id: str) -> dict[str, object]:
        report = self.gateway_manager.diagnose(gateway_id)
        return self._gateway_diagnostic_payload(report)


__all__ = ["SENSITIVE_NETWORK_OPTIONS", "ServiceAPI"]
