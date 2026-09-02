from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Mapping

from agent_runtime.gateway import normalize_instance_path, normalize_public_url

from ..core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PERMISSION_MODE_CHOICES,
    NetworkConfig,
)
from ..oauth.persistence import canonical_oauth_issuer
GATEWAY_MEMBER_LIFECYCLES = {"persistent", "ephemeral"}
SERVICE_MODES = {"single", "multi"}


def _timestamp() -> int:
    return int(time.time())


def _public_hostname(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    return (urlsplit(raw).hostname or "").lower()


@dataclass(frozen=True, slots=True)
class GatewayChildProfile:
    server_id: str
    name: str
    workspace: Path
    oauth_password: str
    instance_path: str
    public_url: str = ""
    permission_mode: str = "safe"
    lifecycle: str = "persistent"
    allow_network: bool = False
    enable_view_image: bool = True

    def validated(self) -> "GatewayChildProfile":
        server_id = self.server_id.strip()
        if not server_id:
            raise ValueError("Gateway Profile server_id 不能为空。")
        name = self.name.strip()
        if not name:
            raise ValueError("Gateway Profile 名称不能为空。")
        workspace = self.workspace.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError(f"Gateway Profile Workspace 无效: {workspace}")
        password = self.oauth_password.strip()
        if not password:
            raise ValueError("Gateway Profile OAuth 登录密码不能为空。")
        permission_mode = self.permission_mode.strip().lower() or "safe"
        if permission_mode not in PERMISSION_MODE_CHOICES:
            raise ValueError(f"不支持的权限模式: {permission_mode}")
        lifecycle = self.lifecycle.strip().lower() or "persistent"
        if lifecycle not in GATEWAY_MEMBER_LIFECYCLES:
            raise ValueError(f"不支持的 Gateway Profile lifecycle: {lifecycle}")
        return GatewayChildProfile(
            server_id=server_id,
            name=name,
            workspace=workspace,
            oauth_password=password,
            instance_path=normalize_instance_path(self.instance_path),
            public_url=normalize_public_url(self.public_url),
            permission_mode=permission_mode,
            lifecycle=lifecycle,
            allow_network=bool(self.allow_network),
            enable_view_image=bool(self.enable_view_image),
        )


@dataclass(frozen=True, slots=True)
class GatewayProcessConfig:
    public_base_url: str
    profiles: tuple[GatewayChildProfile, ...]
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    def validated(self) -> "GatewayProcessConfig":
        public_base_url = canonical_oauth_issuer(self.public_base_url)
        parsed = urlsplit(public_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Gateway Public URL 必须是完整的 http/https URL。")
        if (parsed.path or "").rstrip("/"):
            raise ValueError(
                "Gateway Public URL 必须只包含 hostname；子 Profile 使用独立 Public Hostname。"
            )
        if not 1 <= int(self.port) <= 65535:
            raise ValueError(f"无效 Gateway 端口: {self.port}")
        profiles = tuple(profile.validated() for profile in self.profiles)
        if not profiles:
            raise ValueError("Gateway 至少需要一个 Profile。")
        ids: set[str] = set()
        paths: set[str] = set()
        hostnames: set[str] = set()
        for profile in profiles:
            if profile.server_id in ids:
                raise ValueError(f"重复 Gateway Profile server_id: {profile.server_id}")
            if profile.instance_path in paths:
                raise ValueError(f"重复 Gateway Profile Path: {profile.instance_path}")
            ids.add(profile.server_id)
            paths.add(profile.instance_path)
            if profile.public_url:
                hostname = (urlsplit(profile.public_url).hostname or "").lower()
                if hostname in hostnames:
                    raise ValueError(f"重复 Gateway Profile Public Hostname: {hostname}")
                hostnames.add(hostname)
        return GatewayProcessConfig(
            public_base_url=public_base_url,
            profiles=profiles,
            host=self.host.strip() or DEFAULT_HOST,
            port=int(self.port),
        )


@dataclass(frozen=True, slots=True)
class GatewayLaunchConfig:
    network: NetworkConfig
    profiles: tuple[GatewayChildProfile, ...]
    mode: str = "multi"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    def validated(self) -> "GatewayLaunchConfig":
        network = self.network.validated()
        host = self.host.strip() or DEFAULT_HOST
        port = int(self.port)
        if not 1 <= port <= 65535:
            raise ValueError(f"无效 Gateway 端口: {port}")
        profiles = tuple(profile.validated() for profile in self.profiles)
        if not profiles:
            raise ValueError("Local MCP Gateway 至少需要一个 Profile。")
        mode = self.mode.strip().lower() or "multi"
        if mode not in SERVICE_MODES:
            raise ValueError(f"不支持的 Service mode: {mode}")
        if mode == "single" and not any(profile.instance_path == "" for profile in profiles):
            raise ValueError("单 Workspace 模式必须包含一个根 Workspace Profile。")
        ids: set[str] = set()
        paths: set[str] = set()
        hostnames: set[str] = set()
        for profile in profiles:
            if profile.server_id in ids:
                raise ValueError(f"重复 Gateway Profile server_id: {profile.server_id}")
            if profile.instance_path in paths:
                raise ValueError(f"重复 Gateway Profile Path: {profile.instance_path}")
            ids.add(profile.server_id)
            paths.add(profile.instance_path)
            if profile.public_url:
                hostname = (urlsplit(profile.public_url).hostname or "").lower()
                if hostname in hostnames:
                    raise ValueError(f"重复 Gateway Profile Public Hostname: {hostname}")
                hostnames.add(hostname)
        if network.public_url:
            parsed = urlsplit(network.public_url)
            if (parsed.path or "").rstrip("/"):
                raise ValueError(
                    "Gateway 固定 Public URL 只能填写 hostname；各 MCP Profile 使用独立 Public Hostname。"
                )
        if network.public_url and profiles[0].public_url:
            if canonical_oauth_issuer(network.public_url) != profiles[0].public_url:
                raise ValueError("服务 Public Hostname 必须与主 Workspace Profile Hostname 一致。")
        return GatewayLaunchConfig(
            network=network,
            profiles=profiles,
            mode=mode,
            host=host,
            port=port,
        )


@dataclass(frozen=True, slots=True)
class GatewayProfileLaunchInfo:
    server_id: str
    name: str
    workspace: Path
    instance_path: str
    local_mcp_url: str
    public_mcp_url: str
    oauth_issuer: str
    lifecycle: str
    public_base_url: str = ""


@dataclass(frozen=True, slots=True)
class GatewayLaunchInfo:
    host: str
    port: int
    public_base_url: str
    tunnel_url: str
    url_mode: str
    profiles: tuple[GatewayProfileLaunchInfo, ...]

    def profile(self, server_id: str) -> GatewayProfileLaunchInfo | None:
        target = server_id.strip()
        return next(
            (profile for profile in self.profiles if profile.server_id == target),
            None,
        )


@dataclass(frozen=True, slots=True)
class GatewayProfileDiagnostic:
    server_id: str
    name: str
    instance_path: str
    ok: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]
    public_base_url: str = ""


@dataclass(frozen=True, slots=True)
class GatewayDiagnosticReport:
    ok: bool
    public_base_url: str
    checked_at: int
    profiles: tuple[GatewayProfileDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class MCPGatewayMember:
    server_id: str
    name: str
    workspace: Path
    oauth_password: str
    instance_path: str
    public_url: str = ""
    permission_mode: str = "safe"
    lifecycle: str = "persistent"
    allow_network: bool = False
    enable_view_image: bool = True

    @classmethod
    def create(
        cls,
        *,
        name: str,
        workspace: Path,
        oauth_password: str,
        instance_path: str,
        public_url: str = "",
        permission_mode: str = "safe",
        lifecycle: str = "persistent",
        allow_network: bool = False,
        enable_view_image: bool = True,
    ) -> "MCPGatewayMember":
        return cls(
            server_id=uuid.uuid4().hex,
            name=name,
            workspace=workspace,
            oauth_password=oauth_password,
            instance_path=instance_path,
            public_url=public_url,
            permission_mode=permission_mode,
            lifecycle=lifecycle,
            allow_network=allow_network,
            enable_view_image=enable_view_image,
        ).validated()

    def validated(self) -> "MCPGatewayMember":
        server_id = self.server_id.strip()
        if not server_id:
            raise ValueError("Gateway Member server_id 不能为空。")
        name = self.name.strip()
        if not name:
            raise ValueError("Gateway Member 名称不能为空。")
        workspace = self.workspace.expanduser()
        password = self.oauth_password.strip()
        permission_mode = self.permission_mode.strip().lower() or "safe"
        if permission_mode not in PERMISSION_MODE_CHOICES:
            raise ValueError(f"不支持的权限模式: {permission_mode}")
        lifecycle = self.lifecycle.strip().lower() or "persistent"
        if lifecycle not in GATEWAY_MEMBER_LIFECYCLES:
            raise ValueError(f"不支持的 Gateway Member lifecycle: {lifecycle}")
        return MCPGatewayMember(
            server_id=server_id,
            name=name,
            workspace=workspace,
            oauth_password=password,
            instance_path=normalize_instance_path(self.instance_path),
            public_url=normalize_public_url(self.public_url),
            permission_mode=permission_mode,
            lifecycle=lifecycle,
            allow_network=bool(self.allow_network),
            enable_view_image=bool(self.enable_view_image),
        )

    def to_child_profile(self) -> GatewayChildProfile:
        value = self.validated()
        return GatewayChildProfile(
            server_id=value.server_id,
            name=value.name,
            workspace=value.workspace,
            oauth_password=value.oauth_password,
            instance_path=value.instance_path,
            public_url=value.public_url,
            permission_mode=value.permission_mode,
            lifecycle=value.lifecycle,
            allow_network=value.allow_network,
            enable_view_image=value.enable_view_image,
        )

    def to_dict(self) -> dict[str, object]:
        value = self.validated()
        return {
            "server_id": value.server_id,
            "name": value.name,
            "workspace": str(value.workspace),
            "oauth_password": value.oauth_password,
            "instance_path": value.instance_path,
            "public_url": value.public_url,
            "permission_mode": value.permission_mode,
            "lifecycle": value.lifecycle,
            "allow_network": value.allow_network,
            "enable_view_image": value.enable_view_image,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MCPGatewayMember":
        return cls(
            server_id=str(value.get("server_id") or ""),
            name=str(value.get("name") or ""),
            workspace=Path(str(value.get("workspace") or "")),
            oauth_password=str(value.get("oauth_password") or ""),
            instance_path=str(value.get("instance_path") or ""),
            public_url=str(value.get("public_url") or ""),
            permission_mode=str(value.get("permission_mode") or "safe"),
            lifecycle=str(value.get("lifecycle") or "persistent"),
            allow_network=bool(value.get("allow_network", False)),
            enable_view_image=bool(value.get("enable_view_image", True)),
        ).validated()


@dataclass(frozen=True, slots=True)
class MCPGatewayProfile:
    gateway_id: str
    name: str
    network: NetworkConfig
    members: tuple[MCPGatewayMember, ...]
    mode: str = "multi"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    created_at: int = field(default_factory=_timestamp)
    updated_at: int = field(default_factory=_timestamp)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        network: NetworkConfig,
        members: tuple[MCPGatewayMember, ...],
        mode: str = "multi",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> "MCPGatewayProfile":
        now = _timestamp()
        return cls(
            gateway_id=uuid.uuid4().hex,
            name=name,
            network=network,
            members=members,
            mode=mode,
            host=host,
            port=port,
            created_at=now,
            updated_at=now,
        ).validated()

    def validated(self) -> "MCPGatewayProfile":
        gateway_id = self.gateway_id.strip()
        if not gateway_id:
            raise ValueError("gateway_id 不能为空。")
        name = self.name.strip()
        if not name:
            raise ValueError("Gateway 名称不能为空。")
        network = self.network.validated()
        members = tuple(member.validated() for member in self.members)
        if not members:
            raise ValueError("Gateway 至少需要一个 Member。")
        mode = self.mode.strip().lower() or "multi"
        if mode not in SERVICE_MODES:
            raise ValueError(f"不支持的 Service mode: {mode}")
        if mode == "single" and not any(
            member.instance_path == "" for member in members
        ):
            raise ValueError("单 Workspace 模式必须包含一个根 Workspace Profile。")
        host = self.host.strip() or DEFAULT_HOST
        port = int(self.port)
        if not 1 <= port <= 65535:
            raise ValueError(f"无效 Gateway 端口: {port}")
        if network.public_url:
            parsed = urlsplit(network.public_url)
            if (parsed.path or "").rstrip("/"):
                raise ValueError(
                    "Gateway 固定 Public URL 只能包含 hostname；Member Path 单独配置。"
                )
        member_ids: set[str] = set()
        member_paths: set[str] = set()
        member_hostnames: set[str] = set()
        for member in members:
            if member.server_id in member_ids:
                raise ValueError(f"重复 Gateway Member server_id: {member.server_id}")
            if member.instance_path in member_paths:
                raise ValueError(f"重复 Gateway Member Path: {member.instance_path}")
            member_ids.add(member.server_id)
            member_paths.add(member.instance_path)
            hostname = _public_hostname(member.public_url)
            if hostname:
                if hostname in member_hostnames:
                    raise ValueError(f"重复 Gateway Member Public Hostname: {hostname}")
                member_hostnames.add(hostname)
        if network.public_url and members[0].public_url:
            if normalize_public_url(network.public_url) != members[0].public_url:
                raise ValueError("服务 Public Hostname 必须与主 Workspace Profile Hostname 一致。")
        return MCPGatewayProfile(
            gateway_id=gateway_id,
            name=name,
            network=network,
            members=members,
            mode=mode,
            host=host,
            port=port,
            created_at=int(self.created_at),
            updated_at=int(self.updated_at),
        )

    def to_launch_config(self) -> GatewayLaunchConfig:
        value = self.validated()
        return GatewayLaunchConfig(
            network=value.network,
            profiles=tuple(member.to_child_profile() for member in value.members),
            mode=value.mode,
            host=value.host,
            port=value.port,
        ).validated()

    def runtime_launch_config(
        self,
        *,
        network: NetworkConfig | None = None,
        oauth_passwords: Mapping[str, str] | None = None,
    ) -> GatewayLaunchConfig:
        """Build a runtime config while preserving the saved Gateway identity."""

        value = self.validated()
        runtime_network = (network or value.network).validated()
        if (
            runtime_network.provider != value.network.provider
            or runtime_network.public_url != value.network.public_url
        ):
            raise ValueError("运行配置与已保存 Gateway 不一致，请先保存配置。")
        passwords = oauth_passwords or {}
        profiles = tuple(
            GatewayChildProfile(
                server_id=member.server_id,
                name=member.name,
                workspace=member.workspace,
                oauth_password=str(
                    passwords.get(member.server_id) or member.oauth_password
                ),
                instance_path=member.instance_path,
                public_url=member.public_url,
                permission_mode=member.permission_mode,
                lifecycle=member.lifecycle,
                allow_network=member.allow_network,
                enable_view_image=member.enable_view_image,
            )
            for member in value.members
        )
        return GatewayLaunchConfig(
            network=runtime_network,
            profiles=profiles,
            mode=value.mode,
            host=value.host,
            port=value.port,
        ).validated()

    def to_dict(self) -> dict[str, object]:
        value = self.validated()
        return {
            "gateway_id": value.gateway_id,
            "name": value.name,
            "host": value.host,
            "port": value.port,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "network": {
                "provider": value.network.provider,
                "public_url": value.network.public_url,
                "options": dict(value.network.options),
            },
            "mode": value.mode,
            "members": [member.to_dict() for member in value.members],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MCPGatewayProfile":
        network_raw = value.get("network")
        if not isinstance(network_raw, dict):
            raise ValueError("Gateway network 字段无效。")
        options_raw = network_raw.get("options")
        options = options_raw if isinstance(options_raw, dict) else {}
        members_raw = value.get("members")
        if not isinstance(members_raw, list):
            raise ValueError("Gateway members 字段无效。")
        migrated_members: list[dict[str, Any]] = []
        for item in members_raw:
            if not isinstance(item, dict):
                continue
            migrated = dict(item)
            if (
                not str(migrated.get("public_url") or "").strip()
                and not str(migrated.get("instance_path") or "").strip().strip("/")
                and str(network_raw.get("public_url") or "").strip()
            ):
                migrated["public_url"] = str(network_raw.get("public_url") or "")
            migrated_members.append(migrated)
        return cls(
            gateway_id=str(value.get("gateway_id") or ""),
            name=str(value.get("name") or ""),
            network=NetworkConfig(
                provider=str(network_raw.get("provider") or "cloudflare"),
                public_url=str(network_raw.get("public_url") or ""),
                options={str(key): str(item) for key, item in options.items()},
            ),
            mode=str(value.get("mode") or "multi"),
            members=tuple(
                MCPGatewayMember.from_dict(item)
                for item in migrated_members
            ),
            host=str(value.get("host") or DEFAULT_HOST),
            port=int(value.get("port") or DEFAULT_PORT),
            created_at=int(value.get("created_at") or _timestamp()),
            updated_at=int(value.get("updated_at") or _timestamp()),
        ).validated()
