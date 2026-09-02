from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)
from agent_runtime.route_probe import ROUTE_PROBE_TOKEN_ENV

from ..core.config import LaunchConfig, NetworkConfig
from ..network.base import NetworkProvider
from ..network.factory import create_network_provider
from ..network.specs import network_provider_spec
from ..oauth.persistence import (
    OAUTH_REGISTRY_FILE_ENV,
    OAUTH_TOKEN_SECRET_ENV,
    canonical_oauth_issuer,
)
from ..runtime.process import LogCallback, check_port_available
from ..servers.launcher import MCPLauncher
from .diagnostics import (
    DIAGNOSTIC_OAUTH_CLIENT_NAME,
    DIAGNOSTIC_STARTUP_GRACE_SECONDS,
    DIAGNOSTIC_USER_AGENT,
    GatewayDiagnostics,
)
from .models import (
    GatewayChildProfile,
    GatewayDiagnosticReport,
    GatewayLaunchConfig,
    GatewayLaunchInfo,
    GatewayProcessConfig,
    GatewayProfileLaunchInfo,
)
from .process import GatewayServerProcess


def _ephemeral_network(network: NetworkConfig) -> bool:
    return (
        network_provider_spec(network.provider).ephemeral_without_public_url
        and not network.public_url
    )


def _effective_profiles(
    profiles: tuple[GatewayChildProfile, ...],
    *,
    ephemeral: bool,
) -> tuple[GatewayChildProfile, ...]:
    if not ephemeral:
        return profiles
    return tuple(
        GatewayChildProfile(
            server_id=profile.server_id,
            name=profile.name,
            workspace=profile.workspace,
            oauth_password=profile.oauth_password,
            instance_path=profile.instance_path,
            public_url=profile.public_url,
            permission_mode=profile.permission_mode,
            lifecycle="ephemeral",
            allow_network=profile.allow_network,
            enable_view_image=profile.enable_view_image,
        )
        for profile in profiles
    )


class MCPGatewayLauncher:
    """Own Gateway lifecycle while delegating public E2E checks to diagnostics."""

    def __init__(
        self,
        log: LogCallback | None = None,
        permission_broker: object | None = None,
    ) -> None:
        self._log_callback = log or (lambda _message: None)
        self._lock = threading.RLock()
        self._provider: NetworkProvider | None = None
        self._gateway = GatewayServerProcess(
            self._log,
            permission_broker=permission_broker,
        )
        self._direct = MCPLauncher(
            self._log,
            permission_broker=permission_broker,
        )
        self._info: GatewayLaunchInfo | None = None
        self._active_mode = "multi"
        self._single_server_id = ""
        self._stopping = False
        self._exit_reason = ""
        self._route_probe_token = ""
        self._last_diagnostic: GatewayDiagnosticReport | None = None
        self._diagnostics = GatewayDiagnostics(self.oauth_registry_file)

    def _log(self, message: str) -> None:
        self._log_callback(message)

    @property
    def info(self) -> GatewayLaunchInfo | None:
        if self._active_mode == "single" and self._direct.info is None:
            return None
        return self._info

    @property
    def exit_reason(self) -> str:
        if self._active_mode == "single":
            return self._direct.exit_reason
        return self._exit_reason

    @property
    def is_running(self) -> bool:
        if self._active_mode == "single":
            return self._direct.is_running
        provider = self._provider
        process = self._gateway.process
        return bool(
            provider
            and process
            and provider.is_running
            and process.poll() is None
            and not self._stopping
        )

    def oauth_registry_file(self, server_id: str) -> Path | None:
        if self._active_mode == "single":
            if server_id.strip() != self._single_server_id:
                return None
            return self._direct.oauth_registry_file
        return self._gateway.oauth_registry_file(server_id)

    @property
    def last_diagnostic(self) -> GatewayDiagnosticReport | None:
        return self._last_diagnostic

    def diagnose(self) -> GatewayDiagnosticReport:
        with self._lock:
            if self._active_mode == "single":
                raise RuntimeError("单 Workspace 模式不需要多 Profile Gateway 自检。")
            if not self.is_running or self._info is None:
                raise RuntimeError("请先启动 Local MCP Gateway，再执行公网自检。")
            info = self._info
            route_probe_token = self._route_probe_token

        report = self._diagnostics.diagnose(info, route_probe_token)
        with self._lock:
            if self._info is info:
                self._last_diagnostic = report
        return report

    def _diagnose_background(self, attempts: int = 8) -> None:
        # Named Tunnel can report its first connected edge before all HTTP/2
        # connections and ingress rules settle. Manual diagnostics remain immediate.
        time.sleep(DIAGNOSTIC_STARTUP_GRACE_SECONDS)
        last_report: GatewayDiagnosticReport | None = None
        for attempt in range(1, attempts + 1):
            with self._lock:
                if self._stopping or self._info is None:
                    return
            try:
                report = self.diagnose()
            except Exception as exc:  # noqa: BLE001 - diagnostic must be non-fatal
                if attempt == attempts:
                    self._log(f"警告：Gateway 公网自检无法完成：{exc}")
                else:
                    time.sleep(0.75)
                continue
            last_report = report
            if report.ok:
                self._log(
                    f"Gateway 公网 E2E 自检通过：{len(report.profiles)} 个 Profile "
                    "的 Hostname、Runtime 与 OAuth metadata 均匹配。"
                )
                return
            if attempt < attempts:
                time.sleep(0.75)
        if last_report is not None:
            failed = [profile.name for profile in last_report.profiles if not profile.ok]
            self._log(
                "警告：Gateway 公网 E2E 自检未通过，但 Gateway 保持运行。"
                f"失败 Profile: {', '.join(failed) or '未知'}"
            )
            for profile in last_report.profiles:
                if profile.ok:
                    continue
                details = "; ".join(profile.errors) or "未返回具体错误"
                self._log(
                    f"Gateway 公网 E2E 失败详情 [{profile.name}] "
                    f"Public={profile.public_base_url or profile.instance_path or '/'}: {details}"
                )

    def _start_network(self, config: GatewayLaunchConfig) -> tuple[str, str]:
        self._provider = create_network_provider(
            config.network.provider,
            self._log,
        )
        network_info = self._provider.start(
            config.host,
            config.port,
            config.network,
        )
        public_base_url = canonical_oauth_issuer(network_info.public_base_url)
        parsed = urlsplit(public_base_url)
        if (parsed.path or "").rstrip("/"):
            raise RuntimeError(
                "Gateway Network Provider 返回了带 Path 的 Public URL；"
                "Gateway 公网入口必须是 hostname 级 URL。"
            )
        return public_base_url, network_info.mode_label

    def _launch_profiles(
        self,
        config: GatewayLaunchConfig,
    ) -> tuple[GatewayChildProfile, ...]:
        ephemeral = _ephemeral_network(config.network)
        profiles = _effective_profiles(config.profiles, ephemeral=ephemeral)
        if ephemeral:
            self._log(
                "Gateway 使用临时公网 hostname：所有 Profile OAuth 状态按 ephemeral session 管理。"
            )
        return profiles

    def _start_gateway_origin(
        self,
        config: GatewayLaunchConfig,
        public_base_url: str,
        profiles: tuple[GatewayChildProfile, ...],
    ) -> None:
        self._gateway.start(
            GatewayProcessConfig(
                public_base_url=public_base_url,
                profiles=profiles,
                host=config.host,
                port=config.port,
            ),
            self._gateway_environment(),
        )

    def _gateway_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        # Profile secrets/broker identities are instance-scoped inside the
        # restricted child config; stale single-profile values must not leak in.
        for name in (
            "AGENT_RUNTIME_OAUTH_PASSWORD",
            "AGENT_RUNTIME_SERVER_URL",
            OAUTH_TOKEN_SECRET_ENV,
            OAUTH_REGISTRY_FILE_ENV,
            BROKER_DIR_ENV,
            BROKER_SECRET_ENV,
            BROKER_SERVER_ID_ENV,
            "AGENT_RUNTIME_OAUTH_CLIENT_ID",
            "AGENT_RUNTIME_OAUTH_CLIENT_SECRET",
        ):
            env.pop(name, None)
        self._route_probe_token = secrets.token_urlsafe(32)
        self._last_diagnostic = None
        self._diagnostics.reset()
        env[ROUTE_PROBE_TOKEN_ENV] = self._route_probe_token
        return env

    @staticmethod
    def _build_launch_info(
        config: GatewayLaunchConfig,
        *,
        public_base_url: str,
        url_mode: str,
        profiles: tuple[GatewayChildProfile, ...],
    ) -> GatewayLaunchInfo:
        profile_info = tuple(
            GatewayProfileLaunchInfo(
                server_id=profile.server_id,
                name=profile.name,
                workspace=profile.workspace,
                instance_path=profile.instance_path,
                public_base_url=(
                    profile.public_url or f"{public_base_url}{profile.instance_path}"
                ),
                local_mcp_url=(
                    f"http://{config.host}:{config.port}{profile.instance_path}/mcp"
                ),
                public_mcp_url=(
                    f"{profile.public_url}/mcp"
                    if profile.public_url
                    else f"{public_base_url}{profile.instance_path}/mcp"
                ),
                oauth_issuer=(
                    profile.public_url or f"{public_base_url}{profile.instance_path}"
                ),
                lifecycle=profile.lifecycle,
            )
            for profile in profiles
        )
        return GatewayLaunchInfo(
            host=config.host,
            port=config.port,
            public_base_url=public_base_url,
            tunnel_url=public_base_url,
            url_mode=url_mode,
            profiles=profile_info,
        )

    def _log_launch_info(self, info: GatewayLaunchInfo) -> None:
        self._log(
            f"Local MCP Gateway 已启动: {info.public_base_url}，"
            f"Profiles: {len(info.profiles)}"
        )
        for profile in info.profiles:
            self._log(f"Gateway Profile [{profile.name}]: {profile.public_mcp_url}")
        if len({profile.public_base_url for profile in info.profiles}) > 1:
            self._log(
                "多 Hostname 模式：请在同一个 Tunnel 中将每个 Profile Hostname "
                f"都回源到 http://{info.host}:{info.port}。"
            )

    def _start_watchers(self, url_mode: str) -> None:
        threading.Thread(target=self._watch_children, daemon=True).start()
        if url_mode == "Cloudflare Named Tunnel":
            threading.Thread(
                target=self._diagnose_background,
                daemon=True,
            ).start()

    def start(self, config: GatewayLaunchConfig) -> GatewayLaunchInfo:
        with self._lock:
            if self.is_running:
                raise RuntimeError("Local MCP Gateway 已经在运行。")
            validated = config.validated()
            if validated.mode == "single":
                return self._start_single(validated)
            self._active_mode = "multi"
            self._single_server_id = ""
            self._stopping = False
            self._exit_reason = ""
            check_port_available(validated.host, validated.port)
            try:
                profiles = self._launch_profiles(validated)
                if validated.network.public_url:
                    # Fixed hostnames may already have connected clients. Make
                    # the origin listen before exposing the tunnel to avoid 502s.
                    public_base_url = canonical_oauth_issuer(
                        validated.network.public_url
                    )
                    self._start_gateway_origin(
                        validated,
                        public_base_url,
                        profiles,
                    )
                    provider_url, url_mode = self._start_network(validated)
                    if provider_url != public_base_url:
                        raise RuntimeError(
                            "Gateway Network Provider 返回的 Public URL 与配置的 OAuth issuer 不一致。"
                        )
                else:
                    # Dynamic tunnels reveal the random issuer before the
                    # profile OAuth configuration can be generated.
                    public_base_url, url_mode = self._start_network(validated)
                    self._start_gateway_origin(
                        validated,
                        public_base_url,
                        profiles,
                    )
                self._gateway.bind_oauth_issuers()
                self._diagnostics.configure_oauth_passwords(
                    {
                        profile.server_id: profile.oauth_password
                        for profile in profiles
                    }
                )
                self._info = self._build_launch_info(
                    validated,
                    public_base_url=public_base_url,
                    url_mode=url_mode,
                    profiles=profiles,
                )
                self._log_launch_info(self._info)
                self._start_watchers(url_mode)
                return self._info
            except Exception:
                self._stop_locked()
                raise

    def _start_single(self, config: GatewayLaunchConfig) -> GatewayLaunchInfo:
        root = next(
            (profile for profile in config.profiles if profile.instance_path == ""),
            None,
        )
        if root is None:
            raise ValueError("单 Workspace 模式缺少根 Workspace Profile。")
        lifecycle = "ephemeral" if _ephemeral_network(config.network) else root.lifecycle
        self._active_mode = "single"
        self._single_server_id = root.server_id
        self._stopping = False
        self._exit_reason = ""
        self._last_diagnostic = None
        self._diagnostics.reset()
        direct_info = self._direct.start(
            LaunchConfig(
                workspace=root.workspace,
                oauth_password=root.oauth_password,
                network=config.network,
                host=config.host,
                port=config.port,
                server_id=root.server_id,
                lifecycle=lifecycle,
                permission_mode=root.permission_mode,
                allow_network=root.allow_network,
                enable_view_image=root.enable_view_image,
            )
        )
        profile_info = GatewayProfileLaunchInfo(
            server_id=root.server_id,
            name=root.name,
            workspace=root.workspace,
            instance_path="",
            public_base_url=direct_info.public_base_url,
            local_mcp_url=direct_info.local_mcp_url,
            public_mcp_url=direct_info.public_mcp_url,
            oauth_issuer=direct_info.public_base_url,
            lifecycle=lifecycle,
        )
        self._info = GatewayLaunchInfo(
            host=config.host,
            port=config.port,
            public_base_url=direct_info.public_base_url,
            tunnel_url=direct_info.tunnel_url,
            url_mode=direct_info.url_mode,
            profiles=(profile_info,),
        )
        self._log(
            "服务以单 Workspace 模式启动；已保存的子 Profile 本次不参与运行。"
        )
        return self._info

    def _watch_children(self) -> None:
        while True:
            with self._lock:
                if self._stopping:
                    return
                provider = self._provider
                process = self._gateway.process
                if provider is None or process is None:
                    return
                if not provider.is_running:
                    self._exit_reason = (
                        f"{provider.display_name} 已退出，退出码: {provider.exit_code}"
                    )
                    self._log(self._exit_reason)
                    self._stop_locked()
                    return
                if process.poll() is not None:
                    self._exit_reason = (
                        f"Agent Runtime Gateway 已退出，退出码: {process.returncode}"
                    )
                    self._log(self._exit_reason)
                    self._stop_locked()
                    return
            time.sleep(0.5)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._stopping = True
        if self._active_mode == "single":
            self._direct.stop()
        else:
            self._gateway.stop()
        if self._provider is not None:
            self._provider.stop()
        self._provider = None
        self._info = None
        self._route_probe_token = ""
        self._last_diagnostic = None
        self._diagnostics.reset()
        self._single_server_id = ""

    def wait(self) -> None:
        while self.is_running:
            time.sleep(0.5)


__all__ = [
    "DIAGNOSTIC_OAUTH_CLIENT_NAME",
    "DIAGNOSTIC_USER_AGENT",
    "MCPGatewayLauncher",
]
