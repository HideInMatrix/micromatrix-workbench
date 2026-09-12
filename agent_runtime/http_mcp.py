"""MCP Streamable HTTP controller."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import weakref
from typing import Any, Protocol

from .core.constants import ENDPOINT_PATH
from .errors import RpcError
from .protocol import (
    HEADER_MISMATCH,
    KNOWN_PROTOCOL_VERSIONS,
    LEGACY_PROTOCOL_VERSIONS,
    dispatch,
    rpc_response_status,
    validate_mirror_headers,
)


MAX_HTTP_BODY_BYTES = 1_048_576
LOGGER = logging.getLogger(__name__)
MCP_SESSION_HEADER = "Mcp-Session-Id"
LEGACY_SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_LEGACY_SESSIONS_PER_RUNTIME = 1024


class _LegacyHTTPSessionStore:
    """Stateful Streamable HTTP sessions for pre-2026 MCP clients only.

    Sessions are deliberately keyed by the concrete Runtime object. A Runtime
    replacement (application/profile restart or version upgrade) therefore
    invalidates every old session without persistence or migration.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: weakref.WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = (
            weakref.WeakKeyDictionary()
        )

    @staticmethod
    def _expired(record: dict[str, Any], now: float) -> bool:
        return now - float(record.get("last_seen", 0.0)) > LEGACY_SESSION_TTL_SECONDS

    def _runtime_sessions(self, runtime: Any) -> dict[str, dict[str, Any]]:
        sessions = self._sessions.get(runtime)
        if sessions is None:
            sessions = {}
            self._sessions[runtime] = sessions
        return sessions

    def _prune(self, sessions: dict[str, dict[str, Any]], now: float) -> None:
        for session_id, record in tuple(sessions.items()):
            if self._expired(record, now):
                sessions.pop(session_id, None)
        if len(sessions) <= MAX_LEGACY_SESSIONS_PER_RUNTIME:
            return
        oldest = sorted(
            sessions.items(),
            key=lambda item: float(item[1].get("last_seen", 0.0)),
        )
        for session_id, _record in oldest[: len(sessions) - MAX_LEGACY_SESSIONS_PER_RUNTIME]:
            sessions.pop(session_id, None)

    def create(self, runtime: Any, *, principal: str, protocol_version: str) -> str:
        now = time.monotonic()
        with self._lock:
            sessions = self._runtime_sessions(runtime)
            self._prune(sessions, now)
            session_id = secrets.token_urlsafe(24)
            sessions[session_id] = {
                "principal": principal,
                "protocol_version": protocol_version,
                "last_seen": now,
            }
            return session_id

    def validate(
        self,
        runtime: Any,
        session_id: str,
        *,
        principal: str,
        protocol_version: str | None,
    ) -> bool:
        now = time.monotonic()
        with self._lock:
            sessions = self._sessions.get(runtime)
            if sessions is None:
                return False
            self._prune(sessions, now)
            record = sessions.get(session_id)
            if record is None or str(record.get("principal") or "") != principal:
                return False
            negotiated = str(record.get("protocol_version") or "")
            if protocol_version and negotiated and protocol_version != negotiated:
                return False
            record["last_seen"] = now
            return True

    def revoke(self, runtime: Any, session_id: str, *, principal: str) -> bool:
        with self._lock:
            sessions = self._sessions.get(runtime)
            if sessions is None:
                return False
            record = sessions.get(session_id)
            if record is None or str(record.get("principal") or "") != principal:
                return False
            sessions.pop(session_id, None)
            return True


class MCPHTTPContext(Protocol):
    runtime: Any
    headers: Any

    def _base_url(self) -> str: ...

    def _instance_prefix(self) -> str: ...

    def _json(
        self,
        status: int,
        payload: Any,
        headers: dict[str, str] | None = None,
    ) -> None: ...

    def _read(self, limit: int) -> bytes: ...

    def send_response(self, code: int, message: str | None = None) -> None: ...

    def send_header(self, keyword: str, value: str) -> None: ...

    def end_headers(self) -> None: ...


def protected_resource_metadata_url(resource: str) -> str:
    """Build the RFC 9728 well-known URL for a concrete resource URI."""

    parsed = urllib.parse.urlsplit(resource)
    resource_path = parsed.path.rstrip("/")
    metadata_path = "/.well-known/oauth-protected-resource"
    if resource_path:
        metadata_path += resource_path
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, metadata_path, "", "")
    )


def _allowed_origin(origin: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    configured = {
        value.strip().rstrip("/")
        for value in os.environ.get("AGENT_RUNTIME_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    return origin.rstrip("/") in configured


class MCPHTTPController:
    """Own MCP authentication, transport validation and JSON-RPC dispatch."""

    def __init__(self) -> None:
        self._legacy_sessions = _LegacyHTTPSessionStore()

    @staticmethod
    def allows_origin(origin: str) -> bool:
        return _allowed_origin(origin)

    def server_card(self, handler: MCPHTTPContext) -> dict[str, Any]:
        base = handler._base_url()
        if handler.runtime.oauth_service:
            auth: dict[str, Any] = {
                "type": "oauth2",
                "scheme": "Bearer",
                "authorizationUrl": f"{base}/oauth/authorize",
                "tokenUrl": f"{base}/oauth/token",
                "registrationUrl": f"{base}/oauth/register",
            }
        elif handler.runtime.auth_token:
            auth = {"type": "bearer", "scheme": "Bearer"}
        else:
            auth = {"type": "none"}
        tools = handler.runtime.list_tools()["tools"]
        config = handler.runtime.oauth_service
        endpoint = ""
        if config and config.resource:
            endpoint = urllib.parse.urlsplit(config.resource).path.rstrip("/")
        if not endpoint:
            prefix = handler._instance_prefix()
            endpoint = f"{prefix}{ENDPOINT_PATH}" if prefix else ENDPOINT_PATH
        return {
            "server": handler.runtime.server_identity(),
            "toolContractRevision": handler.runtime.tool_contract_revision,
            "supportedProtocolVersions": list(KNOWN_PROTOCOL_VERSIONS),
            "transport": {
                "type": "streamable_http",
                "endpoint": endpoint,
                "methods": ["POST", "DELETE", "OPTIONS"],
            },
            "auth": auth,
            "capabilities": {"tools": {"listChanged": False}},
            "tools": {"count": len(tools), "names": [tool["name"] for tool in tools]},
        }

    def get(self, handler: MCPHTTPContext) -> None:
        auth_error = self._auth_error(handler)
        if auth_error is not None:
            self._unauthorized(handler, invalid_token=auth_error == "invalid_token")
            return
        handler._json(
            405,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": "SSE GET stream is not supported",
                },
            },
            {"Allow": "POST"},
        )

    def delete(self, handler: MCPHTTPContext) -> None:
        auth_error = self._auth_error(handler)
        if auth_error is not None:
            self._unauthorized(handler, invalid_token=auth_error == "invalid_token")
            return
        session_id = str(handler.headers.get(MCP_SESSION_HEADER) or "").strip()
        if session_id:
            if not self._legacy_sessions.revoke(
                handler.runtime,
                session_id,
                principal=self._principal(handler),
            ):
                handler._json(
                    404,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32001,
                            "message": "MCP session not found or expired",
                            "data": {"reason": "session_not_found"},
                        },
                    },
                )
                return
            handler.send_response(204)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        handler._json(
            405,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32601,
                    "message": "DELETE is not supported: this endpoint has no sessions to terminate",
                },
            },
            {"Allow": "POST"},
        )

    def post(self, handler: MCPHTTPContext) -> None:
        origin = handler.headers.get("Origin")
        if origin and not _allowed_origin(origin):
            handler._json(403, {"error": "origin_not_allowed"})
            return
        auth_error = self._auth_error(handler)
        if auth_error is not None:
            self._unauthorized(handler, invalid_token=auth_error == "invalid_token")
            return
        request = self._read_request(handler)
        if request is None:
            return
        protocol_version = self._transport_protocol(handler, request)
        if protocol_version is False:
            return
        principal = self._principal(handler)
        params = request.get("params")
        meta = params.get("_meta") if isinstance(params, dict) else None
        is_modern = isinstance(meta, dict) and "io.modelcontextprotocol/protocolVersion" in meta
        method = str(request.get("method") or "")
        issue_legacy_session = False
        if not is_modern:
            if method == "initialize":
                if handler.headers.get(MCP_SESSION_HEADER):
                    handler._json(
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "error": {
                                "code": -32600,
                                "message": "initialize must not reuse an existing MCP session",
                                "data": {"reason": "initialize_with_session"},
                            },
                        },
                    )
                    return
                issue_legacy_session = True
            else:
                session_id = str(handler.headers.get(MCP_SESSION_HEADER) or "").strip()
                if not session_id:
                    handler._json(
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "error": {
                                "code": -32001,
                                "message": "Mcp-Session-Id is required; initialize a new MCP session",
                                "data": {"reason": "session_required"},
                            },
                        },
                    )
                    return
                if not self._legacy_sessions.validate(
                    handler.runtime,
                    session_id,
                    principal=principal,
                    protocol_version=(
                        protocol_version
                        if isinstance(protocol_version, str) and protocol_version in LEGACY_PROTOCOL_VERSIONS
                        else None
                    ),
                ):
                    handler._json(
                        404,
                        {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "error": {
                                "code": -32001,
                                "message": "MCP session not found or expired; initialize again",
                                "data": {"reason": "session_not_found"},
                            },
                        },
                    )
                    return
        self._dispatch(
            handler,
            request,
            protocol_version,
            principal=principal,
            issue_legacy_session=issue_legacy_session,
        )

    def _bearer(self, handler: MCPHTTPContext) -> str | None:
        value = handler.headers.get("Authorization", "")
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return None

    def _auth_error(self, handler: MCPHTTPContext) -> str | None:
        if not handler.runtime.auth_enabled():
            return None
        token = self._bearer(handler)
        if not token:
            return "missing_token"
        if handler.runtime.auth_token and secrets.compare_digest(
            token,
            handler.runtime.auth_token,
        ):
            return None
        config = handler.runtime.oauth_service
        if config and config.tokens.validate_access_token(token):
            return None
        return "invalid_token"

    def _principal(self, handler: MCPHTTPContext) -> str:
        token = self._bearer(handler)
        if not token:
            return "anonymous"
        config = handler.runtime.oauth_service
        if config:
            client_id = config.tokens.access_token_client_id(token)
            if client_id:
                return f"oauth-client:{client_id}"
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _unauthorized(
        self,
        handler: MCPHTTPContext,
        *,
        invalid_token: bool = False,
    ) -> None:
        base = handler._base_url()
        config = handler.runtime.oauth_service
        resource = (
            config.resource
            if config and config.resource
            else f"{base}{ENDPOINT_PATH}"
        )
        metadata = protected_resource_metadata_url(resource)
        challenge = (
            'Bearer realm="micromatrix-workbench", '
            f'resource_metadata="{metadata}", scope="mcp"'
        )
        if invalid_token:
            challenge += (
                ', error="invalid_token", '
                'error_description="The access token is invalid or expired."'
            )
        message = (
            "The access token is invalid or expired."
            if invalid_token
            else "Unauthorized"
        )
        handler._json(
            401,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32000,
                    "message": message,
                    "data": {
                        "reason": "invalid_token" if invalid_token else "missing_token"
                    },
                },
            },
            {"WWW-Authenticate": challenge},
        )

    @staticmethod
    def _duplicate_mirror_header(handler: MCPHTTPContext) -> str | None:
        for header in (
            "MCP-Protocol-Version",
            "Mcp-Method",
            "Mcp-Name",
            MCP_SESSION_HEADER,
        ):
            if len(handler.headers.get_all(header) or ()) > 1:
                return header
        return None

    def _read_request(self, handler: MCPHTTPContext) -> dict[str, Any] | None:
        if handler.headers.get_content_type().lower() != "application/json":
            handler._json(
                415,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Content-Type must be application/json",
                    },
                },
            )
            return None
        if handler.headers.get("Content-Length") is None:
            handler._json(
                411,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Content-Length is required"},
                },
            )
            return None
        try:
            request = json.loads(handler._read(MAX_HTTP_BODY_BYTES))
        except ConnectionAbortedError:
            # The upstream request was cancelled; the socket is already
            # closing, so emitting a misleading protocol 400 only adds noise.
            return None
        except (ValueError, json.JSONDecodeError) as exc:
            handler._json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                },
            )
            return None
        if isinstance(request, list):
            handler._json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "JSON-RPC batch requests are not supported by Streamable HTTP",
                    },
                },
            )
            return None
        if not isinstance(request, dict):
            handler._json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
            )
            return None
        return request

    def _transport_protocol(
        self,
        handler: MCPHTTPContext,
        request: dict[str, Any],
    ) -> str | None | bool:
        method = request.get("method")
        raw_params = request.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        protocol_version = handler.headers.get("MCP-Protocol-Version")
        duplicate = self._duplicate_mirror_header(handler)
        if duplicate is not None:
            handler._json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": HEADER_MISMATCH,
                        "message": f"{duplicate} must appear exactly once",
                        "data": {"header": duplicate, "reason": "duplicate"},
                    },
                },
            )
            return False
        if isinstance(method, str):
            try:
                validate_mirror_headers(
                    method,
                    params,
                    version_header=protocol_version,
                    method_header=handler.headers.get("Mcp-Method"),
                    name_header=handler.headers.get("Mcp-Name"),
                )
            except RpcError as exc:
                handler._json(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            **({"data": exc.data} if exc.data is not None else {}),
                        },
                    },
                )
                return False
        meta = params.get("_meta")
        has_embedded_version = (
            isinstance(meta, dict)
            and "io.modelcontextprotocol/protocolVersion" in meta
        )
        if (
            protocol_version
            and protocol_version not in KNOWN_PROTOCOL_VERSIONS
            and not has_embedded_version
        ):
            handler._json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32600,
                        "message": "Unsupported MCP protocol version",
                        "data": {
                            "supported": list(KNOWN_PROTOCOL_VERSIONS),
                            "received": protocol_version,
                        },
                    },
                },
            )
            return False
        return protocol_version

    def _dispatch(
        self,
        handler: MCPHTTPContext,
        request: dict[str, Any],
        protocol_version: str | None,
        *,
        principal: str,
        issue_legacy_session: bool = False,
    ) -> None:
        try:
            response = dispatch(
                handler.runtime,
                request,
                transport_protocol_version=(
                    protocol_version
                    if protocol_version in LEGACY_PROTOCOL_VERSIONS
                    else None
                ),
                principal=principal,
            )
        except Exception as exc:
            LOGGER.exception("Unhandled MCP dispatch failure")
            handler._json(
                # A syntactically valid JSON-RPC request reached MCP dispatch.
                # Keep implementation failures inside JSON-RPC instead of
                # returning HTTP 5xx, which reverse proxies often rewrite into
                # an opaque 502 and hide the structured error payload.
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": {"exception_type": type(exc).__name__},
                    },
                },
            )
            return
        if response is None:
            handler.send_response(202)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        headers: dict[str, str] = {}
        if issue_legacy_session and isinstance(response.get("result"), dict):
            negotiated = str(response["result"].get("protocolVersion") or "")
            if negotiated in LEGACY_PROTOCOL_VERSIONS:
                headers[MCP_SESSION_HEADER] = self._legacy_sessions.create(
                    handler.runtime,
                    principal=principal,
                    protocol_version=negotiated,
                )
        handler._json(rpc_response_status(request, response), response, headers or None)


__all__ = ["MCPHTTPController", "protected_resource_metadata_url"]
