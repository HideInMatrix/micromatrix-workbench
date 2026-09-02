from __future__ import annotations

import base64
import hashlib
import json
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

try:
    import certifi
except ImportError:  # pragma: no cover - desktop requirements normally include it
    certifi = None

from agent_runtime.route_probe import (
    ROUTE_PROBE_HEADER,
    ROUTE_PROBE_PATH,
    workspace_fingerprint,
)

from .models import (
    GatewayDiagnosticReport,
    GatewayLaunchInfo,
    GatewayProfileDiagnostic,
    GatewayProfileLaunchInfo,
)


DIAGNOSTIC_OAUTH_CLIENT_NAME = "MicroMatrix Workbench E2E Diagnostic"
DIAGNOSTIC_OAUTH_REDIRECT_URI = "https://micromatrix.invalid/oauth/callback"
DIAGNOSTIC_USER_AGENT = "MicroMatrix-Workbench-E2E/1.0"
DIAGNOSTIC_HTTP_TIMEOUT_SECONDS = 9.0
DIAGNOSTIC_STARTUP_GRACE_SECONDS = 1.5


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class GatewayDiagnostics:
    """Perform public Gateway runtime and OAuth diagnostics without owning lifecycle."""

    def __init__(
        self,
        registry_file_for: Callable[[str], Path | None],
    ) -> None:
        self._registry_file_for = registry_file_for
        self._oauth_passwords: dict[str, str] = {}
        self._oauth_clients: dict[str, str] = {}

    def configure_oauth_passwords(self, passwords: dict[str, str]) -> None:
        self._oauth_passwords = dict(passwords)
        self._oauth_clients = {}

    def reset(self) -> None:
        self._oauth_passwords = {}
        self._oauth_clients = {}

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
        cached = self._oauth_clients.get(profile.server_id)
        if cached:
            return cached

        registry_file = self._registry_file_for(profile.server_id)
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
                        self._oauth_clients[profile.server_id] = client_id
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
        self._oauth_clients[profile.server_id] = client_id
        return client_id

    def _check_oauth_token_exchange(self, profile: GatewayProfileLaunchInfo) -> None:
        if profile.server_id not in self._oauth_passwords:
            raise RuntimeError("当前 Gateway Session 缺少 OAuth Password，无法执行 Token 自检")
        password = self._oauth_passwords[profile.server_id]
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
        payload, _ = self._json_get(url, headers=headers)
        if payload.get("workspace_fingerprint") != expected_fingerprint:
            raise RuntimeError(mismatch_message)

    def _check_server_card(
        self,
        info: GatewayLaunchInfo,
        profile: GatewayProfileLaunchInfo,
    ) -> None:
        del info
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
        del info
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

    def diagnose(
        self,
        info: GatewayLaunchInfo,
        route_probe_token: str,
    ) -> GatewayDiagnosticReport:
        if not route_probe_token:
            raise RuntimeError("当前 Gateway Session 没有可用的内部诊断 Token。")
        profiles = tuple(
            self._profile_diagnostic(info, profile, route_probe_token)
            for profile in info.profiles
        )
        return GatewayDiagnosticReport(
            ok=bool(profiles) and all(profile.ok for profile in profiles),
            public_base_url=info.public_base_url,
            checked_at=int(time.time()),
            profiles=profiles,
        )


__all__ = [
    "DIAGNOSTIC_HTTP_TIMEOUT_SECONDS",
    "DIAGNOSTIC_OAUTH_CLIENT_NAME",
    "DIAGNOSTIC_OAUTH_REDIRECT_URI",
    "DIAGNOSTIC_STARTUP_GRACE_SECONDS",
    "DIAGNOSTIC_USER_AGENT",
    "GatewayDiagnostics",
]
