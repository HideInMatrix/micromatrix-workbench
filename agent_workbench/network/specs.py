"""UI-agnostic metadata for supported public network providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkOptionSpec:
    key: str
    label: str
    secret: bool = False
    span: str = "1"

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "secret": self.secret,
            "span": self.span,
        }


@dataclass(frozen=True, slots=True)
class NetworkProviderSpec:
    key: str
    label: str
    options: tuple[NetworkOptionSpec, ...] = ()
    supports_public_url: bool = True
    ephemeral_without_public_url: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "supports_public_url": self.supports_public_url,
            "ephemeral_without_public_url": self.ephemeral_without_public_url,
            "options": [option.to_dict() for option in self.options],
        }


NETWORK_PROVIDER_SPECS = (
    NetworkProviderSpec(
        key="cloudflare",
        label="Cloudflare Tunnel",
        ephemeral_without_public_url=True,
        options=(NetworkOptionSpec("tunnel_token", "隧道令牌", True, "2"),),
    ),
    NetworkProviderSpec(
        key="frp",
        label="FRP",
        options=(
            NetworkOptionSpec("executable", "frpc 路径", span="2"),
            NetworkOptionSpec("config_file", "frpc 配置文件", span="2"),
        ),
    ),
    NetworkProviderSpec(
        key="ngrok",
        label="ngrok",
        ephemeral_without_public_url=True,
        options=(
            NetworkOptionSpec("executable", "ngrok 路径"),
            NetworkOptionSpec("authtoken", "认证令牌", True),
        ),
    ),
    NetworkProviderSpec(
        key="tailscale",
        label="Tailscale Funnel",
        supports_public_url=False,
        options=(NetworkOptionSpec("executable", "Tailscale 路径", span="2"),),
    ),
    NetworkProviderSpec(key="external", label="自定义公网 URL"),
)
NETWORK_PROVIDER_BY_KEY = {spec.key: spec for spec in NETWORK_PROVIDER_SPECS}
NETWORK_PROVIDER_CHOICES = tuple(NETWORK_PROVIDER_BY_KEY)


def network_provider_spec(key: str) -> NetworkProviderSpec:
    try:
        return NETWORK_PROVIDER_BY_KEY[key.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"不支持的网络提供方案: {key}") from exc


def network_provider_catalog() -> list[dict[str, object]]:
    return [spec.to_dict() for spec in NETWORK_PROVIDER_SPECS]
