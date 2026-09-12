from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.atomic_io import atomic_write_json

from ..core.config import DEFAULT_HOST, DEFAULT_PORT, NetworkConfig
from ..core.settings import settings_dir
from .models import MCPServerProfile, _public_hostname_identity, _timestamp


SERVER_PROFILE_SCHEMA_VERSION = 1
LEGACY_GATEWAY_PROFILE_SCHEMA_VERSION = 1
LEGACY_NETWORK_SECRET_OPTIONS = {"tunnel_token", "authtoken"}


class ServerProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (settings_dir() / "servers.json")
        self.legacy_gateway_path = self.path.with_name("gateways.json")

    def list(self) -> list[MCPServerProfile]:
        self._migrate_legacy_gateways()
        return self._load_profiles()

    def _load_profiles(self) -> list[MCPServerProfile]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Server Profile 文件损坏: {self.path}") from exc
        if not isinstance(payload, dict) or payload.get("version") != SERVER_PROFILE_SCHEMA_VERSION:
            raise RuntimeError(f"Server Profile 文件格式不受支持: {self.path}")
        raw_profiles = payload.get("servers")
        if not isinstance(raw_profiles, list):
            raise RuntimeError(f"Server Profile servers 字段无效: {self.path}")
        profiles: list[MCPServerProfile] = []
        try:
            for item in raw_profiles:
                if not isinstance(item, dict):
                    raise ValueError("profile entry must be an object")
                profiles.append(MCPServerProfile.from_dict(item))
        except ValueError as exc:
            raise RuntimeError(f"Server Profile 内容无效: {self.path}") from exc
        return profiles

    @staticmethod
    def _next_unused_port(
        host: str,
        start: int,
        endpoints: set[tuple[str, int]],
    ) -> int:
        for port in range(max(1, int(start)), 65536):
            if (host, port) not in endpoints:
                return port
        raise RuntimeError("没有可用的 TCP 端口可迁移旧 Work。")

    def _migrate_legacy_gateways(self) -> None:
        legacy = self.legacy_gateway_path
        if not legacy.exists():
            return
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"旧 Gateway 配置文件损坏: {legacy}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != LEGACY_GATEWAY_PROFILE_SCHEMA_VERSION
            or not isinstance(payload.get("gateways"), list)
        ):
            raise RuntimeError(f"旧 Gateway 配置文件格式不受支持: {legacy}")

        profiles = self._load_profiles()
        ids = {profile.server_id for profile in profiles}
        endpoints = {(profile.host, profile.port) for profile in profiles}
        hostnames = {
            hostname
            for hostname in (
                _public_hostname_identity(profile.network.public_url)
                for profile in profiles
            )
            if hostname
        }
        for raw_gateway in payload["gateways"]:
            if not isinstance(raw_gateway, dict):
                continue
            gateway_name = str(raw_gateway.get("name") or "Legacy Work").strip()
            gateway_host = str(raw_gateway.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST
            gateway_port = int(raw_gateway.get("port") or DEFAULT_PORT)
            gateway_created_at = int(raw_gateway.get("created_at") or _timestamp())
            gateway_updated_at = int(raw_gateway.get("updated_at") or gateway_created_at)
            network_raw = raw_gateway.get("network")
            if not isinstance(network_raw, dict):
                network_raw = {}
            options_raw = network_raw.get("options")
            options = (
                {
                    str(key): str(value)
                    for key, value in options_raw.items()
                    if str(key) not in LEGACY_NETWORK_SECRET_OPTIONS
                }
                if isinstance(options_raw, dict)
                else {}
            )
            provider = str(network_raw.get("provider") or "cloudflare")
            gateway_public_url = str(network_raw.get("public_url") or "").strip()
            members = raw_gateway.get("members")
            if not isinstance(members, list):
                continue
            next_port_start = gateway_port
            for index, raw_member in enumerate(members):
                if not isinstance(raw_member, dict):
                    continue
                server_id = str(raw_member.get("server_id") or "").strip()
                if not server_id or server_id in ids:
                    continue
                instance_path = str(raw_member.get("instance_path") or "").strip().strip("/")
                member_name = str(raw_member.get("name") or f"Work {index + 1}").strip()
                name = (
                    gateway_name
                    if not instance_path
                    else f"{gateway_name} / {member_name}"
                )
                public_url = str(raw_member.get("public_url") or "").strip()
                if not public_url and not instance_path:
                    public_url = gateway_public_url
                hostname = _public_hostname_identity(public_url)
                if hostname and hostname in hostnames:
                    public_url = ""
                    hostname = ""
                port = self._next_unused_port(
                    gateway_host,
                    next_port_start,
                    endpoints,
                )
                next_port_start = port + 1
                profile = MCPServerProfile(
                    server_id=server_id,
                    name=name,
                    workspace=Path(str(raw_member.get("workspace") or "")),
                    oauth_password=str(raw_member.get("oauth_password") or ""),
                    network=NetworkConfig(
                        provider=provider,
                        public_url=public_url,
                        options=dict(options),
                    ),
                    host=gateway_host,
                    port=port,
                    lifecycle=str(raw_member.get("lifecycle") or "persistent"),
                    enabled=False,
                    permission_mode=str(raw_member.get("permission_mode") or "safe"),
                    allow_network=bool(raw_member.get("allow_network", False)),
                    enable_view_image=bool(raw_member.get("enable_view_image", True)),
                    toolchains=tuple(raw_member.get("toolchains") or ()),
                    created_at=gateway_created_at,
                    updated_at=gateway_updated_at,
                ).validated()
                profiles.append(profile)
                ids.add(server_id)
                endpoints.add((gateway_host, port))
                if hostname:
                    hostnames.add(hostname)

        self._save(profiles)
        sanitized = json.loads(json.dumps(payload))
        for raw_gateway in sanitized.get("gateways", []):
            if not isinstance(raw_gateway, dict):
                continue
            network_raw = raw_gateway.get("network")
            if not isinstance(network_raw, dict):
                continue
            options_raw = network_raw.get("options")
            if not isinstance(options_raw, dict):
                continue
            for key in LEGACY_NETWORK_SECRET_OPTIONS:
                options_raw.pop(key, None)
        archive = legacy.with_name("gateways.migrated.json")
        atomic_write_json(archive, sanitized, mode=0o600)
        legacy.unlink()

    def get(self, server_id: str) -> MCPServerProfile | None:
        target = server_id.strip()
        for profile in self.list():
            if profile.server_id == target:
                return profile
        return None

    def next_default_port(self, start: int = DEFAULT_PORT) -> int:
        used = {profile.port for profile in self.list()}
        for port in range(max(1, int(start)), 65536):
            if port not in used:
                return port
        raise RuntimeError("没有可用的 TCP 端口可分配。")

    def create(
        self,
        *,
        name: str,
        workspace: Path,
        oauth_password: str,
        network: NetworkConfig | None = None,
        host: str = DEFAULT_HOST,
        port: int | None = None,
        lifecycle: str | None = None,
        enabled: bool = False,
        permission_mode: str = "safe",
        allow_network: bool = False,
        enable_view_image: bool = True,
        toolchains: tuple[dict, ...] = (),
    ) -> MCPServerProfile:
        selected_port = self.next_default_port() if port is None else int(port)
        profile = MCPServerProfile.create(
            name=name,
            workspace=workspace,
            oauth_password=oauth_password,
            network=network,
            host=host,
            port=selected_port,
            lifecycle=lifecycle,
            enabled=enabled,
            permission_mode=permission_mode,
            allow_network=allow_network,
            enable_view_image=enable_view_image,
            toolchains=toolchains,
        )
        profiles = self.list()
        profiles.append(profile)
        self._save(profiles)
        return profile

    def save(self, profile: MCPServerProfile) -> MCPServerProfile:
        validated = profile.validated()
        profiles = self.list()
        replacement = MCPServerProfile(
            server_id=validated.server_id,
            name=validated.name,
            workspace=validated.workspace,
            oauth_password=validated.oauth_password,
            network=validated.network,
            host=validated.host,
            port=validated.port,
            lifecycle=validated.lifecycle,
            enabled=validated.enabled,
            permission_mode=validated.permission_mode,
            allow_network=validated.allow_network,
            enable_view_image=validated.enable_view_image,
            toolchains=validated.toolchains,
            created_at=validated.created_at,
            updated_at=_timestamp(),
        )
        for index, existing in enumerate(profiles):
            if existing.server_id == replacement.server_id:
                profiles[index] = replacement
                self._save(profiles)
                return replacement
        profiles.append(replacement)
        self._save(profiles)
        return replacement

    def delete(self, server_id: str) -> bool:
        target = server_id.strip()
        profiles = self.list()
        remaining = [profile for profile in profiles if profile.server_id != target]
        if len(remaining) == len(profiles):
            return False
        self._save(remaining)
        return True

    def _save(self, profiles: list[MCPServerProfile]) -> None:
        ids: set[str] = set()
        endpoints: set[tuple[str, int]] = set()
        public_hostnames: set[str] = set()
        validated_profiles: list[MCPServerProfile] = []
        for profile in profiles:
            validated = profile.validated()
            if validated.server_id in ids:
                raise ValueError(f"重复 server_id: {validated.server_id}")
            ids.add(validated.server_id)
            endpoint = (validated.host, validated.port)
            if endpoint in endpoints:
                raise ValueError(
                    f"多个 Server Profile 不能配置相同地址: {validated.host}:{validated.port}"
                )
            endpoints.add(endpoint)
            public_hostname = _public_hostname_identity(validated.network.public_url)
            if public_hostname:
                if public_hostname in public_hostnames:
                    raise ValueError(
                        "每个 Work 必须使用独立 Public Hostname；"
                        "同一个 hostname 不能绑定多个 Work。"
                    )
                public_hostnames.add(public_hostname)
            validated_profiles.append(validated)

        payload = {
            "version": SERVER_PROFILE_SCHEMA_VERSION,
            "servers": [profile.to_dict() for profile in validated_profiles],
        }
        atomic_write_json(self.path, payload, mode=0o600)
