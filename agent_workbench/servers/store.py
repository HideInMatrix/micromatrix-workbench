from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.atomic_io import atomic_write_json

from ..core.config import DEFAULT_HOST, DEFAULT_PORT, NetworkConfig
from ..core.settings import settings_dir
from .models import MCPServerProfile, _public_hostname_identity, _timestamp


SERVER_PROFILE_SCHEMA_VERSION = 1


class ServerProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (settings_dir() / "servers.json")

    def list(self) -> list[MCPServerProfile]:
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
        permission_mode: str = "safe",
        allow_network: bool = False,
        enable_view_image: bool = True,
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
            permission_mode=permission_mode,
            allow_network=allow_network,
            enable_view_image=enable_view_image,
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
            permission_mode=validated.permission_mode,
            allow_network=validated.allow_network,
            enable_view_image=validated.enable_view_image,
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
                        "多个直连 Server Profile 不能配置相同 Public Hostname；"
                        "独立服务请使用独立 hostname；同一 hostname 下需要多个 Workspace 时，"
                        "请在同一个服务中添加 Profile。"
                    )
                public_hostnames.add(public_hostname)
            validated_profiles.append(validated)

        payload = {
            "version": SERVER_PROFILE_SCHEMA_VERSION,
            "servers": [profile.to_dict() for profile in validated_profiles],
        }
        atomic_write_json(self.path, payload, mode=0o600)
