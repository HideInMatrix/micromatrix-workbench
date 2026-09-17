from __future__ import annotations

import json
import os
import threading
import time
from typing import TYPE_CHECKING

from ..core.config import LaunchConfig, LaunchInfo
from ..network.base import NetworkProvider
from ..network.factory import create_network_provider
from ..oauth.persistence import (
    OAUTH_REGISTRY_FILE_ENV,
    OAUTH_TOKEN_SECRET_ENV,
    OAuthPersistence,
    bind_server_oauth_issuer,
    canonical_oauth_issuer,
    prepare_ephemeral_oauth_persistence,
    prepare_issuer_oauth_persistence,
)
from ..runtime.mcp_process import MCPServerProcess
from ..runtime.process import LogCallback, check_port_available

if TYPE_CHECKING:
    from ..runtime.permission_broker import DesktopPermissionBroker


def _desktop_os_sandbox_preference() -> str:
    """Return the fail-closed sandbox level supported by this desktop OS.

    Windows currently provides kernel-enforced process isolation through a
    Restricted Token + Job Object, but does not yet provide the filesystem and
    network confinement required by the full ``require`` policy.  Keep Windows
    fail-closed at the process boundary instead of silently falling back to
    application-only policy.
    """

    return "require-process" if os.name == "nt" else "require"


class MCPLauncher:
    def __init__(
        self,
        log: LogCallback | None = None,
        permission_broker: "DesktopPermissionBroker | None" = None,
    ):
        self._log_callback = log or (lambda _message: None)
        self._lock = threading.RLock()
        self._provider: NetworkProvider | None = None
        self._mcp = MCPServerProcess(self._log)
        self._info: LaunchInfo | None = None
        self._oauth_persistence: OAuthPersistence | None = None
        self._stopping = False
        self._exit_reason = ""
        self._permission_broker = permission_broker

    def _log(self, message: str) -> None:
        self._log_callback(message)

    @property
    def info(self) -> LaunchInfo | None:
        return self._info

    @property
    def exit_reason(self) -> str:
        return self._exit_reason

    @property
    def oauth_registry_file(self):
        persistence = self._oauth_persistence
        return persistence.registry_file if persistence is not None else None

    @property
    def oauth_is_ephemeral(self) -> bool:
        persistence = self._oauth_persistence
        return bool(persistence and persistence.ephemeral)

    @property
    def is_running(self) -> bool:
        provider = self._provider
        mcp = self._mcp.process
        return bool(
            self._info
            and provider
            and provider.is_running
            and mcp
            and mcp.poll() is None
            and not self._stopping
        )

    def start(self, config: LaunchConfig) -> LaunchInfo:
        with self._lock:
            if self.is_running:
                raise RuntimeError("MCP 服务已经在运行。")
            config = config.validated()
            self._stopping = False
            self._exit_reason = ""
            check_port_available(config.host, config.port)
            try:
                self._provider = create_network_provider(
                    config.network.provider,
                    self._log,
                )
                # When the public issuer is already known, make the local
                # origin listen before exposing/connecting the tunnel. This
                # removes the deterministic startup window where a saved URL
                # could reach the edge while the Runtime port was still down.
                public_base_url = (
                    canonical_oauth_issuer(config.network.public_url)
                    if config.network.public_url
                    else ""
                )
                network_info = None
                if not public_base_url:
                    network_info = self._provider.start(
                        config.host,
                        config.port,
                        config.network,
                    )
                    public_base_url = canonical_oauth_issuer(
                        network_info.public_base_url
                    )
                if config.lifecycle == "ephemeral":
                    oauth_persistence = prepare_ephemeral_oauth_persistence(
                        config.server_id or "session"
                    )
                else:
                    issuer = public_base_url
                    oauth_persistence = prepare_issuer_oauth_persistence(issuer)
                self._oauth_persistence = oauth_persistence
                env = os.environ.copy()
                # CLI .env files may carry advanced Runtime settings (for
                # example OS sandbox policy). LaunchConfig filters out values
                # owned by the launcher before they reach this boundary.
                env.update(config.runtime_environment)
                sandbox_preference = _desktop_os_sandbox_preference()
                env.update(
                    {
                        "AGENT_RUNTIME_OAUTH_PASSWORD": config.oauth_password,
                        "AGENT_RUNTIME_SERVER_URL": public_base_url,
                        OAUTH_TOKEN_SECRET_ENV: oauth_persistence.token_secret_hex,
                        OAUTH_REGISTRY_FILE_ENV: str(oauth_persistence.registry_file),
                        "AGENT_RUNTIME_OAUTH_CIMD_ENABLED": (
                            "0" if oauth_persistence.ephemeral else "1"
                        ),
                        "AGENT_RUNTIME_ALLOW_NETWORK": "1" if config.allow_network else "0",
                        "AGENT_RUNTIME_ENABLE_VIEW_IMAGE": "1" if config.enable_view_image else "0",
                        "AGENT_RUNTIME_TOOLCHAINS": json.dumps(config.toolchains),
                        "AGENT_RUNTIME_OS_SANDBOX": sandbox_preference,
                    }
                )
                if sandbox_preference == "require-process":
                    self._log(
                        "Windows Runtime 强制 Restricted Token + Job Object 进程隔离；"
                        "当前文件系统/网络隔离级别仍为 partial。"
                    )
                if self._permission_broker is not None:
                    env.update(
                        self._permission_broker.child_environment(config.server_id)
                    )
                # Locally persisted clients use RFC 7591 Dynamic Client
                # Registration. CIMD clients are resolved dynamically by the
                # Runtime and recorded separately as read-only observations.
                # Explicitly discard legacy preregistration environment
                # variables so old shells/settings cannot silently re-enable
                # the previous fixed-client behaviour.
                env.pop("AGENT_RUNTIME_OAUTH_CLIENT_ID", None)
                env.pop("AGENT_RUNTIME_OAUTH_CLIENT_SECRET", None)
                if oauth_persistence.ephemeral:
                    self._log(
                        "OAuth 临时 Session 已创建：Quick Tunnel 使用 DCR；"
                        "本次 Tunnel 停止后 client_id 将失效。"
                    )
                else:
                    self._log(
                        "OAuth 状态持久化已启用：DCR client_id 与 token secret 按 issuer 跨重启保留。"
                    )
                self._mcp.start(config, env)
                if network_info is None:
                    network_info = self._provider.start(
                        config.host,
                        config.port,
                        config.network,
                    )
                    provider_url = canonical_oauth_issuer(
                        network_info.public_base_url
                    )
                    if provider_url != public_base_url:
                        raise RuntimeError(
                            "Network Provider 返回的 Public URL 与配置的 OAuth issuer 不一致。"
                        )
                if not oauth_persistence.ephemeral and config.server_id:
                    # Commit the profile -> issuer management binding only
                    # after both the origin and provider are healthy.
                    bind_server_oauth_issuer(config.server_id, public_base_url)
                assert network_info is not None
                self._info = LaunchInfo(
                    workspace=config.workspace,
                    local_mcp_url=f"http://{config.host}:{config.port}/mcp",
                    tunnel_url=public_base_url,
                    public_base_url=public_base_url,
                    public_mcp_url=f"{public_base_url}/mcp",
                    url_mode=network_info.mode_label,
                )
                self._log(f"内网穿透已就绪，MCP 已启动: {self._info.public_mcp_url}")
                threading.Thread(target=self._watch_children, daemon=True).start()
                return self._info
            except Exception:
                self._stop_locked()
                raise

    def _watch_children(self) -> None:
        while True:
            with self._lock:
                if self._stopping:
                    return
                provider = self._provider
                mcp = self._mcp.process
                if provider is None or mcp is None:
                    return
                if not provider.is_running:
                    self._exit_reason = (
                        f"{provider.display_name} 已退出，退出码: {provider.exit_code}"
                    )
                    self._log(self._exit_reason)
                    self._stop_locked()
                    return
                if mcp.poll() is not None:
                    self._exit_reason = (
                        f"Agent Runtime 已退出，退出码: {mcp.returncode}"
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
        self._mcp.stop()
        if self._provider is not None:
            self._provider.stop()
        if self._oauth_persistence is not None:
            self._oauth_persistence.cleanup()
        self._oauth_persistence = None
        self._provider = None
        self._info = None

    def wait(self) -> None:
        while self.is_running:
            time.sleep(0.5)
