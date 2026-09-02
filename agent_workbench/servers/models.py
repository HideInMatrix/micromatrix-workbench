from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from ..core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PERMISSION_MODE_CHOICES,
    LaunchConfig,
    NetworkConfig,
    default_lifecycle,
)
SERVER_LIFECYCLES = {"persistent", "ephemeral"}


def _timestamp() -> int:
    return int(time.time())


def _public_hostname_identity(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return (parsed.hostname or "").lower()


@dataclass(slots=True)
class MCPServerProfile:
    server_id: str
    name: str
    workspace: Path
    oauth_password: str
    network: NetworkConfig = field(default_factory=NetworkConfig)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    lifecycle: str = "persistent"
    permission_mode: str = "safe"
    allow_network: bool = False
    enable_view_image: bool = True
    created_at: int = field(default_factory=_timestamp)
    updated_at: int = field(default_factory=_timestamp)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        workspace: Path,
        oauth_password: str,
        network: NetworkConfig | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        lifecycle: str | None = None,
        permission_mode: str = "safe",
        allow_network: bool = False,
        enable_view_image: bool = True,
    ) -> "MCPServerProfile":
        resolved_network = (network or NetworkConfig()).validated()
        now = _timestamp()
        return cls(
            server_id=uuid.uuid4().hex,
            name=name,
            workspace=workspace,
            oauth_password=oauth_password,
            network=resolved_network,
            host=host,
            port=port,
            lifecycle=lifecycle or default_lifecycle(resolved_network),
            permission_mode=permission_mode,
            allow_network=allow_network,
            enable_view_image=enable_view_image,
            created_at=now,
            updated_at=now,
        ).validated()

    def validated(self) -> "MCPServerProfile":
        server_id = self.server_id.strip()
        if not server_id:
            raise ValueError("server_id 不能为空。")

        name = self.name.strip()
        if not name:
            raise ValueError("服务名称不能为空。")

        host = self.host.strip() or DEFAULT_HOST
        if not 1 <= int(self.port) <= 65535:
            raise ValueError(f"无效端口: {self.port}")

        lifecycle = self.lifecycle.strip().lower()
        if lifecycle not in SERVER_LIFECYCLES:
            raise ValueError(f"不支持的 Server lifecycle: {lifecycle}")
        permission_mode = self.permission_mode.strip().lower() or "safe"
        if permission_mode not in PERMISSION_MODE_CHOICES:
            raise ValueError(f"不支持的权限模式: {permission_mode}")

        network = self.network.validated()
        workspace = self.workspace.expanduser()
        oauth_password = self.oauth_password.strip()

        return MCPServerProfile(
            server_id=server_id,
            name=name,
            workspace=workspace,
            oauth_password=oauth_password,
            network=network,
            host=host,
            port=int(self.port),
            lifecycle=lifecycle,
            permission_mode=permission_mode,
            allow_network=bool(self.allow_network),
            enable_view_image=bool(self.enable_view_image),
            created_at=int(self.created_at),
            updated_at=int(self.updated_at),
        )

    def to_launch_config(self) -> LaunchConfig:
        return LaunchConfig(
            workspace=self.workspace,
            oauth_password=self.oauth_password,
            network=self.network,
            host=self.host,
            port=self.port,
            server_id=self.server_id,
            lifecycle=self.lifecycle,
            permission_mode=self.permission_mode,
            allow_network=self.allow_network,
            enable_view_image=self.enable_view_image,
        ).validated()

    def to_dict(self) -> dict[str, Any]:
        profile = self.validated()
        return {
            "server_id": profile.server_id,
            "name": profile.name,
            "workspace": str(profile.workspace),
            "oauth_password": profile.oauth_password,
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
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MCPServerProfile":
        network_raw = raw.get("network")
        if not isinstance(network_raw, dict):
            network_raw = {}
        options_raw = network_raw.get("options")
        if not isinstance(options_raw, dict):
            options_raw = {}
        try:
            profile = cls(
                server_id=str(raw["server_id"]),
                name=str(raw["name"]),
                workspace=Path(str(raw["workspace"])),
                oauth_password=str(raw["oauth_password"]),
                host=str(raw.get("host", DEFAULT_HOST)),
                port=int(raw.get("port", DEFAULT_PORT)),
                lifecycle=str(raw.get("lifecycle", "persistent")),
                permission_mode=str(raw.get("permission_mode", "safe")),
                allow_network=bool(raw.get("allow_network", False)),
                enable_view_image=bool(raw.get("enable_view_image", True)),
                created_at=int(raw.get("created_at", _timestamp())),
                updated_at=int(raw.get("updated_at", _timestamp())),
                network=NetworkConfig(
                    provider=str(network_raw.get("provider", "cloudflare")),
                    public_url=str(network_raw.get("public_url", "")),
                    options={str(key): str(value) for key, value in options_raw.items()},
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Server Profile 数据格式无效。") from exc
        return profile.validated()

