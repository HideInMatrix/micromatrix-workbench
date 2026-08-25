from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

try:
    import certifi
except ImportError:  # pragma: no cover - desktop requirements normally include it
    certifi = None

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)
from agent_runtime.route_probe import (
    ROUTE_PROBE_HEADER,
    ROUTE_PROBE_PATH,
    ROUTE_PROBE_TOKEN_ENV,
    workspace_fingerprint,
)

from .config import DEFAULT_HOST, DEFAULT_PORT, LaunchConfig, NetworkConfig
from .gateway_process import (
    GatewayChildProfile,
    GatewayProcessConfig,
    GatewayServerProcess,
)
from .network import NetworkProvider, create_network_provider
from .launcher import MCPLauncher
from .oauth_persistence import (
    OAUTH_REGISTRY_FILE_ENV,
    OAUTH_TOKEN_SECRET_ENV,
    canonical_oauth_issuer,
)
from .process_utils import LogCallback, check_port_available


DIAGNOSTIC_OAUTH_CLIENT_NAME = "MicroMatrix Workbench E2E Diagnostic"
DIAGNOSTIC_OAUTH_REDIRECT_URI = "https://micromatrix.invalid/oauth/callback"
DIAGNOSTIC_USER_AGENT = "MicroMatrix-Workbench-E2E/1.0"
DIAGNOSTIC_HTTP_TIMEOUT_SECONDS = 9.0
DIAGNOSTIC_STARTUP_GRACE_SECONDS = 1.5


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


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
        if mode not in {"single", "multi"}:
            raise ValueError(f"不支持的 Service mode: {mode}")
        if mode == "single" and not any(
            profile.instance_path == "" for profile in profiles
        ):
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


def _ephemeral_network(network: NetworkConfig) -> bool:
    return network.provider in {"cloudflare", "ngrok"} and not network.public_url


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
    """Launch one public network entry and one local multi-profile Gateway."""

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
        self._diagnostic_oauth_passwords: dict[str, str] = {}
        self._diagnostic_oauth_clients: dict[str, str] = {}

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

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        context = ssl.create_default_context()
        if certifi is not None:
            try:
                context.load_verify_locations(cafile=certifi.where())
            except OSError:
                pass
        return context

    def _json_get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DIAGNOSTIC_HTTP_TIMEOUT_SECONDS,
    ) -> tuple[dict[str, object], dict[str, str]]:
        request = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": DIAGNOSTIC_USER_AGENT,
                **(headers or {}),
            },
            method="GET",
        )
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=self._ssl_context(),
        ) as response:
            raw = json.loads(response.read().decode("utf-8"))
            if not isinstance(raw, dict):
                raise RuntimeError(f"诊断端点返回了非对象 JSON: {url}")
            return raw, {key.lower(): value for key, value in response.headers.items()}

    def _json_post(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout: float = DIAGNOSTIC_HTTP_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DIAGNOSTIC_USER_AGENT,
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._ssl_context(),
            )
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._oauth_http_error(exc)) from exc
        with response:
            raw = json.loads(response.read().decode("utf-8"))
            if not isinstance(raw, dict):
                raise RuntimeError(f"诊断端点返回了非对象 JSON: {url}")
            return raw

    def _form_post_json(
        self,
        url: str,
        fields: dict[str, str],
        *,
        timeout: float = DIAGNOSTIC_HTTP_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(fields).encode("utf-8"),
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": DIAGNOSTIC_USER_AGENT,
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._ssl_context(),
            )
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._oauth_http_error(exc)) from exc
        with response:
            raw = json.loads(response.read().decode("utf-8"))
            if not isinstance(raw, dict):
                raise RuntimeError(f"诊断端点返回了非对象 JSON: {url}")
            return raw

    @staticmethod
    def _oauth_http_error(exc: urllib.error.HTTPError) -> str:
        try:
            body = exc.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(body)
        except (OSError, json.JSONDecodeError):
            return f"OAuth endpoint 返回 HTTP {exc.code}"
        if not isinstance(payload, dict):
            return f"OAuth endpoint 返回 HTTP {exc.code}"
        error = (
            str(payload.get("error") or "oauth_error")
            .replace("\r", " ")
            .replace("\n", " ")[:80]
        )
        description = (
            str(payload.get("error_description") or "")
            .replace("\r", " ")
            .replace("\n", " ")[:240]
        )
        suffix = f": {description}" if description else ""
        return f"OAuth endpoint HTTP {exc.code} {error}{suffix}"

    def _form_post_redirect(
        self,
        url: str,
        fields: dict[str, str],
        *,
        timeout: float = DIAGNOSTIC_HTTP_TIMEOUT_SECONDS,
    ) -> str:
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(fields).encode("utf-8"),
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": DIAGNOSTIC_USER_AGENT,
            },
            method="POST",
        )
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ssl_context()),
            _NoRedirectHandler(),
        )
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                status = exc.code
                exc.read()
                raise RuntimeError(f"OAuth authorize 返回 HTTP {status}") from exc
            location = exc.headers.get("Location", "").strip()
            exc.read()
            if not location:
                raise RuntimeError("OAuth authorize redirect 缺少 Location") from exc
            return location
        with response:
            location = response.headers.get("Location", "").strip()
            if response.status not in {301, 302, 303, 307, 308} or not location:
                raise RuntimeError(
                    f"OAuth authorize 预期 302 redirect，实际 HTTP {response.status}"
                )
            return location

    def _diagnostic_client_id(self, profile: GatewayProfileLaunchInfo) -> str:
        cached = self._diagnostic_oauth_clients.get(profile.server_id)
        if cached:
            return cached

        registry_file = self.oauth_registry_file(profile.server_id)
        if registry_file is not None and registry_file.exists():
            try:
                payload = json.loads(registry_file.read_text(encoding="utf-8"))
                clients = payload.get("clients", []) if isinstance(payload, dict) else []
                for item in (clients if isinstance(clients, list) else []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("client_name") != DIAGNOSTIC_OAUTH_CLIENT_NAME:
                        continue
                    if item.get("token_endpoint_auth_method") != "none":
                        continue
                    redirects = item.get("redirect_uris")
                    if redirects != [DIAGNOSTIC_OAUTH_REDIRECT_URI]:
                        continue
                    client_id = item.get("client_id")
                    if isinstance(client_id, str) and client_id:
                        self._diagnostic_oauth_clients[profile.server_id] = client_id
                        return client_id
            except (OSError, json.JSONDecodeError):
                pass

        registration = self._json_post(
            f"{profile.oauth_issuer}/oauth/register",
            {
                "client_name": DIAGNOSTIC_OAUTH_CLIENT_NAME,
                "redirect_uris": [DIAGNOSTIC_OAUTH_REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "application_type": "web",
            },
        )
        client_id = registration.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise RuntimeError("OAuth DCR 自检未返回 client_id")
        self._diagnostic_oauth_clients[profile.server_id] = client_id
        return client_id

    def _check_oauth_token_exchange(self, profile: GatewayProfileLaunchInfo) -> None:
        if profile.server_id not in self._diagnostic_oauth_passwords:
            raise RuntimeError("当前 Gateway Session 缺少 OAuth Password，无法执行 Token 自检")
        password = self._diagnostic_oauth_passwords[profile.server_id]
        client_id = self._diagnostic_client_id(profile)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        state = secrets.token_urlsafe(12)
        location = self._form_post_redirect(
            f"{profile.oauth_issuer}/oauth/authorize",
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": DIAGNOSTIC_OAUTH_REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": profile.public_mcp_url,
                "scope": "mcp offline_access",
                "state": state,
                "password": password,
            },
        )
        parsed = urllib.parse.urlsplit(location)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        code_values = query.get("code", [])
        state_values = query.get("state", [])
        if len(code_values) != 1 or not code_values[0]:
            raise RuntimeError("OAuth authorize redirect 未返回 authorization code")
        if state_values != [state]:
            raise RuntimeError("OAuth authorize redirect state 不匹配")
        token = self._form_post_json(
            f"{profile.oauth_issuer}/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code_values[0],
                "client_id": client_id,
                "redirect_uri": DIAGNOSTIC_OAUTH_REDIRECT_URI,
                "code_verifier": verifier,
                "resource": profile.public_mcp_url,
            },
        )
        if not isinstance(token.get("access_token"), str) or not token.get("access_token"):
            raise RuntimeError("OAuth token endpoint 未返回 access_token")
        if str(token.get("token_type") or "").lower() != "bearer":
            raise RuntimeError(f"OAuth token_type 非 Bearer: {token.get('token_type')}")
        if not isinstance(token.get("refresh_token"), str) or not token.get("refresh_token"):
            raise RuntimeError("OAuth token endpoint 未返回 refresh_token")

    def _check_runtime_probe(
        self,
        url: str,
        *,
        route_probe_token: str,
        expected_fingerprint: str,
        mismatch_message: str,
        host_header: str = "",
    ) -> None:
        headers = {ROUTE_PROBE_HEADER: route_probe_token}
        if host_header:
            headers["Host"] = host_header
        payload, _ = self._json_get(
            url,
            headers=headers,
        )
        if payload.get("workspace_fingerprint") != expected_fingerprint:
            raise RuntimeError(mismatch_message)

    def _check_server_card(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> None:
        public_base = profile.public_base_url or profile.oauth_issuer
        card, _ = self._json_get(f"{public_base}/")
        transport = card.get("transport")
        endpoint = transport.get("endpoint") if isinstance(transport, dict) else None
        expected_endpoint = urlsplit(profile.public_mcp_url).path
        if endpoint != expected_endpoint:
            raise RuntimeError(f"Server Card endpoint 不匹配: {endpoint}")

    def _check_oauth_authorization_metadata(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> None:
        parsed = urlsplit(profile.oauth_issuer)
        issuer_path = (parsed.path or "").rstrip("/")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        url = f"{origin}/.well-known/oauth-authorization-server{issuer_path}"
        metadata, _ = self._json_get(url)
        expected_issuer = profile.oauth_issuer
        if metadata.get("issuer") != expected_issuer:
            raise RuntimeError(f"OAuth issuer 不匹配: {metadata.get('issuer')}")
        if metadata.get("authorization_endpoint") != f"{expected_issuer}/oauth/authorize":
            raise RuntimeError("OAuth authorization_endpoint 不匹配")
        if metadata.get("token_endpoint") != f"{expected_issuer}/oauth/token":
            raise RuntimeError("OAuth token_endpoint 不匹配")

    @staticmethod
    def _protected_metadata_url(
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> str:
        del info
        parsed = urlsplit(profile.public_mcp_url)
        resource_path = (parsed.path or "").rstrip("/")
        return (
            f"{parsed.scheme}://{parsed.netloc}"
            f"/.well-known/oauth-protected-resource{resource_path}"
        )

    def _check_oauth_protected_resource(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> None:
        metadata, _ = self._json_get(self._protected_metadata_url(info, profile))
        if metadata.get("resource") != profile.public_mcp_url:
            raise RuntimeError(f"OAuth protected resource 不匹配: {metadata.get('resource')}")
        authorization_servers = metadata.get("authorization_servers")
        if (
            not isinstance(authorization_servers, list)
            or profile.oauth_issuer not in authorization_servers
        ):
            raise RuntimeError("OAuth authorization_servers 未包含当前 Profile issuer")

    def _check_mcp_auth_challenge(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> None:
        request = urllib.request.Request(
            profile.public_mcp_url,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": DIAGNOSTIC_USER_AGENT,
            },
            method="GET",
        )
        try:
            urllib.request.urlopen(
                request,
                timeout=DIAGNOSTIC_HTTP_TIMEOUT_SECONDS,
                context=self._ssl_context(),
            ).close()
            raise RuntimeError("未授权 MCP GET 意外成功")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError(f"未授权 MCP GET 返回 HTTP {exc.code}") from exc
            challenge = exc.headers.get("WWW-Authenticate", "")
            if self._protected_metadata_url(info, profile) not in challenge:
                raise RuntimeError("WWW-Authenticate resource_metadata 不匹配")

    def _profile_diagnostic(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
        route_probe_token: str,
    ) -> GatewayProfileDiagnostic:
        checks: list[str] = []
        errors: list[str] = []
        expected_fingerprint = workspace_fingerprint(profile.workspace)
        public_base = profile.public_base_url or profile.oauth_issuer
        legacy_public_base = f"{info.public_base_url}{profile.instance_path}"
        host_routed_child = bool(
            profile.instance_path
            and public_base.rstrip("/") != legacy_public_base.rstrip("/")
        )
        local_probe = (
            f"http://{info.host}:{info.port}{ROUTE_PROBE_PATH}"
            if host_routed_child
            else f"http://{info.host}:{info.port}{profile.instance_path}{ROUTE_PROBE_PATH}"
        )
        public_probe = f"{public_base}{ROUTE_PROBE_PATH}"

        try:
            self._check_runtime_probe(
                local_probe,
                route_probe_token=route_probe_token,
                expected_fingerprint=expected_fingerprint,
                mismatch_message="本地 Gateway 命中了错误的 Workspace Runtime",
                host_header=(urlsplit(public_base).netloc if host_routed_child else ""),
            )
            checks.append("local_path_runtime")
        except Exception as exc:  # noqa: BLE001 - aggregate diagnostic failures
            errors.append(f"local_path_runtime: {exc}")

        try:
            self._check_runtime_probe(
                public_probe,
                route_probe_token=route_probe_token,
                expected_fingerprint=expected_fingerprint,
                mismatch_message="公网 Hostname 命中了错误的 Workspace Runtime",
            )
            checks.append("public_path_runtime")
        except Exception as exc:  # noqa: BLE001 - aggregate diagnostic failures
            errors.append(f"public_path_runtime: {exc}")

        try:
            self._check_server_card(info, profile)
            checks.append("server_card")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"server_card: {exc}")

        try:
            self._check_oauth_authorization_metadata(info, profile)
            checks.append("oauth_authorization_metadata")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"oauth_authorization_metadata: {exc}")

        try:
            self._check_oauth_protected_resource(info, profile)
            checks.append("oauth_protected_resource")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"oauth_protected_resource: {exc}")

        try:
            self._check_mcp_auth_challenge(info, profile)
            checks.append("mcp_auth_challenge")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mcp_auth_challenge: {exc}")

        try:
            self._check_oauth_token_exchange(profile)
            checks.append("oauth_token_exchange")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"oauth_token_exchange: {exc}")

        return GatewayProfileDiagnostic(
            server_id=profile.server_id,
            name=profile.name,
            instance_path=profile.instance_path,
            ok=not errors,
            checks=tuple(checks),
            errors=tuple(errors),
            public_base_url=profile.public_base_url or profile.oauth_issuer,
        )

    def diagnose(self) -> GatewayDiagnosticReport:
        with self._lock:
            if self._active_mode == "single":
                raise RuntimeError("单 Workspace 模式不需要多 Profile Gateway 自检。")
            if not self.is_running or self._info is None:
                raise RuntimeError("请先启动 Local MCP Gateway，再执行公网自检。")
            info = self._info
            route_probe_token = self._route_probe_token
        if not route_probe_token:
            raise RuntimeError("当前 Gateway Session 没有可用的内部诊断 Token。")
        profiles = tuple(
            self._profile_diagnostic(info, profile, route_probe_token)
            for profile in info.profiles
        )
        report = GatewayDiagnosticReport(
            ok=bool(profiles) and all(profile.ok for profile in profiles),
            public_base_url=info.public_base_url,
            checked_at=int(time.time()),
            profiles=profiles,
        )
        with self._lock:
            if self._info is info:
                self._last_diagnostic = report
        return report

    def _diagnose_background(self, attempts: int = 8) -> None:
        # Named Tunnel can report its first connected edge before the remaining
        # HTTP/2 connections and published ingress are fully settled. Give the
        # public path a short grace period before the first automatic E2E pass;
        # manual diagnostics still run immediately.
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

    def _gateway_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        # Gateway profile secrets/broker identities are instance scoped inside
        # its restricted temporary config. Never let stale single-profile
        # environment variables leak into Gateway Runtime.
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
                public_base_url=(profile.public_url or f"{public_base_url}{profile.instance_path}"),
                local_mcp_url=(
                    f"http://{config.host}:{config.port}{profile.instance_path}/mcp"
                ),
                public_mcp_url=(
                    f"{profile.public_url}/mcp"
                    if profile.public_url
                    else f"{public_base_url}{profile.instance_path}/mcp"
                ),
                oauth_issuer=(profile.public_url or f"{public_base_url}{profile.instance_path}"),
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
                public_base_url, url_mode = self._start_network(validated)
                profiles = self._launch_profiles(validated)
                child_config = GatewayProcessConfig(
                    public_base_url=public_base_url,
                    profiles=profiles,
                    host=validated.host,
                    port=validated.port,
                )
                self._gateway.start(child_config, self._gateway_environment())
                self._diagnostic_oauth_passwords = {
                    profile.server_id: profile.oauth_password for profile in profiles
                }
                self._diagnostic_oauth_clients = {}
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
        self._diagnostic_oauth_passwords = {}
        self._diagnostic_oauth_clients = {}
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
        self._diagnostic_oauth_passwords = {}
        self._diagnostic_oauth_clients = {}
        self._single_server_id = ""

    def wait(self) -> None:
        while self.is_running:
            time.sleep(0.5)

