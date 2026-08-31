from __future__ import annotations

import re

from ..config import NetworkConfig
from ..process_utils import LogCallback
from ..resources import resolve_cloudflared
from .base import NetworkProviderResult
from .process import ProcessNetworkProvider


TUNNEL_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
REQUEST_CANCELLATION_MARKERS = (
    "incoming request ended abruptly: context canceled",
    "failed to proxy http: incoming request ended abruptly: context canceled",
)


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
                    "http2",
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
                    "http2",
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
