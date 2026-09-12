from __future__ import annotations

import json
import re
import secrets
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    import certifi
except ImportError:  # pragma: no cover - desktop requirements normally include it
    certifi = None

from agent_runtime.route_probe import ROUTE_PROBE_HEADER, ROUTE_PROBE_PATH

from ..core.config import NetworkConfig
from ..core.resources import resolve_cloudflared
from ..runtime.process import LogCallback
from .base import NetworkProviderResult
from .process import ProcessNetworkProvider


TUNNEL_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
REQUEST_CANCELLATION_MARKERS = (
    "incoming request ended abruptly: context canceled",
    "failed to proxy http: incoming request ended abruptly: context canceled",
)


@dataclass(frozen=True, slots=True)
class NamedTunnelProbeResult:
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def probe_named_tunnel_route(
    public_base_url: str,
    route_probe_token: str,
    expected_fingerprint: str,
    *,
    timeout: float = 4.0,
) -> NamedTunnelProbeResult:
    """Check that a fixed Cloudflare hostname reaches the expected Runtime."""

    context = ssl.create_default_context()
    if certifi is not None:
        try:
            context.load_verify_locations(cafile=certifi.where())
        except OSError:
            pass
    request = urllib.request.Request(
        f"{public_base_url.rstrip('/')}"
        f"{ROUTE_PROBE_PATH}?nonce={secrets.token_urlsafe(8)}",
        headers={
            ROUTE_PROBE_HEADER: route_probe_token,
            "Cache-Control": "no-cache",
            "Connection": "close",
            "User-Agent": "MicroMatrix-Workbench-Tunnel-Health/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read(8193)
            if len(body) > 8192:
                return NamedTunnelProbeResult(
                    "unavailable", "route probe response exceeded 8 KiB"
                )
            raw = json.loads(body.decode("utf-8"))
            if not isinstance(raw, dict):
                return NamedTunnelProbeResult(
                    "unavailable", "route probe returned non-object JSON"
                )
            actual = str(raw.get("workspace_fingerprint") or "")
            if actual != expected_fingerprint:
                return NamedTunnelProbeResult(
                    "mismatch",
                    f"workspace fingerprint mismatch: {actual or 'missing'}",
                )
            return NamedTunnelProbeResult("ok")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return NamedTunnelProbeResult("blocked", f"HTTP {exc.code}")
        if exc.code == 404:
            return NamedTunnelProbeResult("mismatch", "HTTP 404 route probe not found")
        return NamedTunnelProbeResult("unavailable", f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return NamedTunnelProbeResult("unavailable", str(exc.reason or exc))
    except (TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return NamedTunnelProbeResult("unavailable", str(exc))


def is_request_cancellation_log(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in REQUEST_CANCELLATION_MARKERS)


class CloudflareProvider(ProcessNetworkProvider):
    key = "cloudflare"
    display_name = "Cloudflare Tunnel"
    process_name = "cloudflared"

    def __init__(self, log: LogCallback):
        super().__init__(log)

    def validate_config(self, config: NetworkConfig) -> None:
        validated = config.validated()
        public_url = validated.public_url
        tunnel_token = validated.options.get("tunnel_token", "").strip()
        if bool(public_url) != bool(tunnel_token):
            raise ValueError(
                "Cloudflare 固定 Public URL 与 Tunnel Token 必须同时填写；"
                "都留空则使用 Quick Tunnel。"
            )

    def start(self, host: str, port: int, config: NetworkConfig) -> NetworkProviderResult:
        config = config.validated()
        self.validate_config(config)
        public_url = config.public_url
        tunnel_token = config.options.get("tunnel_token", "").strip()
        executable = resolve_cloudflared()
        # Keep Cloudflare's adaptive transport negotiation enabled. ``auto``
        # prefers QUIC and falls back to HTTP/2 when UDP is unavailable.
        tunnel_protocol = "auto"
        if public_url:
            self._log(f"启动 Cloudflare Named Tunnel: {executable}")
            self._log(f"固定 Public URL: {public_url}")
            self._log(
                "Named Tunnel Token 只标识当前 Tunnel；多台电脑请使用独立 hostname、"
                "独立 Tunnel 和独立 Token。"
            )
            self._log(
                "当前 Tunnel 的 Published Application / Origin 应指向: "
                f"http://{host}:{port}"
            )
            self.spawn(
                [
                    str(executable),
                    "tunnel",
                    "--protocol",
                    tunnel_protocol,
                    "run",
                    "--token",
                    tunnel_token,
                ],
                prefix="cloudflared",
            )
            self.wait_for_line(
                lambda line: "registered tunnel connection" in line.lower(),
                timeout=60.0,
                description="Cloudflare Named Tunnel 建立连接",
            )
            self._log("Named Tunnel 已连接 Cloudflare Edge。")
            resolved = public_url
        else:
            self._log(f"启动 Cloudflare Quick Tunnel: {executable}")
            self.spawn(
                [
                    str(executable),
                    "tunnel",
                    "--protocol",
                    tunnel_protocol,
                    "--url",
                    f"http://{host}:{port}",
                ],
                prefix="cloudflared",
            )
            line = self.wait_for_line(
                lambda value: bool(TUNNEL_URL_PATTERN.search(value)),
                timeout=60.0,
                description="Cloudflare Quick Tunnel URL",
            )
            match = TUNNEL_URL_PATTERN.search(line)
            assert match is not None
            resolved = match.group(0)
            self._log(f"Quick Tunnel URL: {resolved}")
        return NetworkProviderResult(
            provider=self.key,
            public_base_url=resolved,
            mode_label="Cloudflare Named Tunnel" if public_url else "Cloudflare Quick Tunnel",
        )

    def format_output_line(self, prefix: str, line: str) -> str:
        if is_request_cancellation_log(line):
            return (
                "[cloudflared][request-cancelled] 上游客户端/中转层取消了进行中的 "
                f"HTTP 请求；这不等于 Tunnel 进程退出。raw={line}"
            )
        return super().format_output_line(prefix, line)
