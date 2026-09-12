from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BROKER_DIR_ENV = "AGENT_RUNTIME_PERMISSION_BROKER_DIR"
BROKER_SECRET_ENV = "AGENT_RUNTIME_PERMISSION_BROKER_SECRET"
BROKER_SERVER_ID_ENV = "AGENT_RUNTIME_PERMISSION_BROKER_SERVER_ID"
BROKER_VERSION = 1
BROKER_REQUEST_TTL_SECONDS = 120
HOST_TOOL_RESOLUTION_TTL_SECONDS = 15
HOST_CAPABILITY_TTL_SECONDS = 30
HOST_IDENTITY_TTL_SECONDS = 45
HOST_HEALTH_MAX_AGE_MS = 750
HOST_ACK_TIMEOUT_SECONDS = 0.75
WORKFLOW_APPROVAL_TTL_SECONDS = 86_400
WORKFLOW_APPROVAL_KIND = "workflow_approval"
HOST_TOOL_RESOLUTION_KIND = "host_tool_resolution"
HOST_CAPABILITY_KIND = "host_capability"
HOST_IDENTITY_KIND = "host_identity_execution"
HOST_HEALTH_KIND = "host_health"
HOST_HEALTH_FILE = "host-health.json"
HOST_ACK_KIND = "host_ack"
HOST_SUPERVISOR_KIND = "host_supervisor"
HOST_SUPERVISOR_FILE = "host-supervisor.json"
HOST_DIAGNOSTICS_KIND = "host_diagnostics"
HOST_DIAGNOSTICS_FILE = "host-diagnostics.json"
HOST_CONTROL_KIND = "host_control"
HOST_WORKER_CONTROL_KIND = "host_worker_control"
_SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|credential|api[_-]?key|password|passwd|private)",
    re.I,
)


def canonical_payload(payload: dict[str, Any]) -> bytes:
    value = {key: item for key, item in payload.items() if key != "signature"}
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_payload(secret: bytes, payload: dict[str, Any]) -> str:
    return hmac.new(secret, canonical_payload(payload), hashlib.sha256).hexdigest()


def verify_payload(secret: bytes, payload: dict[str, Any]) -> bool:
    signature = payload.get("signature")
    return isinstance(signature, str) and hmac.compare_digest(
        signature,
        sign_payload(secret, payload),
    )


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def redact_for_display(value: Any, *, key: str = "") -> Any:
    if key and _SENSITIVE_KEY_RE.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): redact_for_display(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_for_display(item) for item in value[:100]]
    if isinstance(value, str):
        return value if len(value) <= 1200 else value[:1197] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1200]


@dataclass(frozen=True, slots=True)
class LocalPermissionDecision:
    status: str
    scope: str = "once"
    registration: dict[str, Any] | None = None

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @property
    def denied(self) -> bool:
        return self.status == "denied"

    @property
    def session(self) -> bool:
        return self.approved and self.scope == "session"


@dataclass(frozen=True, slots=True)
class LocalHostToolResolution:
    status: str
    proposal: dict[str, Any] | None = None
    error: str = ""
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LocalHostCapabilityResult:
    status: str
    result: dict[str, Any] | None = None
    error: str = ""
    details: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True, slots=True)
class LocalHostIdentityResult:
    status: str
    result: dict[str, Any] | None = None
    error: str = ""
    details: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class LocalPermissionBrokerClient:
    def __init__(self, directory: Path, secret: bytes, server_id: str) -> None:
        self.directory = directory.resolve()
        self.secret = secret
        self.server_id = server_id
        self.runtime_instance_id = secrets.token_urlsafe(16)
        self._last_health_marker: tuple[str, int] | None = None
        self._last_health_seen_monotonic = 0.0

    def _host_health(self) -> dict[str, Any] | None:
        try:
            raw = json.loads((self.directory / HOST_HEALTH_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != HOST_HEALTH_KIND
        ):
            return None
        generation = str(raw.get("generation") or "")
        updated_at_ms = int(raw.get("updated_at_ms") or 0)
        wall_age_ms = int(time.time() * 1000) - updated_at_ms
        if not generation or updated_at_ms <= 0 or wall_age_ms < 0 or wall_age_ms > HOST_HEALTH_MAX_AGE_MS:
            return None
        marker = (generation, updated_at_ms)
        now_monotonic = time.monotonic()
        if marker != self._last_health_marker:
            self._last_health_marker = marker
            self._last_health_seen_monotonic = now_monotonic
        elif (
            self._last_health_seen_monotonic > 0
            and (now_monotonic - self._last_health_seen_monotonic) * 1000 > HOST_HEALTH_MAX_AGE_MS
        ):
            return None
        return raw

    def _read_signed_file(self, path: Path, *, kind: str) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != kind
        ):
            return None
        return raw

    def _await_host_ack(
        self,
        *,
        request_id: str,
        request_kind: str,
        generation: str,
        ack_path: Path,
        response_path: Path,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        deadline = time.monotonic() + HOST_ACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            ack = self._read_signed_file(ack_path, kind=HOST_ACK_KIND)
            if ack is not None:
                if (
                    str(ack.get("request_id") or "") == request_id
                    and str(ack.get("request_kind") or "") == request_kind
                    and str(ack.get("generation") or "") == generation
                ):
                    response = self._read_signed_file(response_path, kind=request_kind)
                    return ack, response, None
            response = self._read_signed_file(response_path, kind=request_kind)
            if response is not None:
                # Worker always writes ACK before dispatching the provider.  If
                # the provider completed so quickly that its response becomes
                # visible first, briefly continue until the corresponding ACK
                # is readable so diagnostics never lose host_ack_at_ms.
                time.sleep(0.005)
                continue
            health = self._host_health()
            if health is None:
                return None, None, {
                    "stage": "ack",
                    "cause_code": "HOST_DISCONNECTED",
                    "request_id": request_id,
                    "generation": generation,
                    "host_ack_at_ms": None,
                    "provider_start_at_ms": None,
                }
            if str(health.get("generation") or "") != generation:
                return None, None, {
                    "stage": "ack",
                    "cause_code": "HOST_GENERATION_CHANGED",
                    "request_id": request_id,
                    "generation": generation,
                    "host_ack_at_ms": None,
                    "provider_start_at_ms": None,
                }
            time.sleep(0.02)
        return None, None, {
            "stage": "ack",
            "cause_code": "HOST_ACK_TIMEOUT",
            "request_id": request_id,
            "generation": generation,
            "host_ack_at_ms": None,
            "provider_start_at_ms": None,
        }

    @staticmethod
    def _host_request_details(
        *,
        request_id: str,
        generation: str,
        queued_at_ms: int,
        stage: str,
        cause_code: str,
        ack: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "generation": generation,
            "stage": stage,
            "cause_code": cause_code,
            "queued_at_ms": queued_at_ms,
            "host_ack_at_ms": (
                int(ack.get("acknowledged_at_ms") or 0) or None
                if isinstance(ack, dict)
                else None
            ),
            "provider_start_at_ms": (
                int(response.get("provider_start_at_ms") or 0) or None
                if isinstance(response, dict)
                else None
            ),
            "responded_at_ms": (
                int(response.get("responded_at_ms") or 0) or None
                if isinstance(response, dict)
                else None
            ),
        }

    @classmethod
    def from_env(cls) -> "LocalPermissionBrokerClient | None":
        raw_directory = os.environ.get(BROKER_DIR_ENV, "").strip()
        raw_secret = os.environ.get(BROKER_SECRET_ENV, "").strip()
        if not raw_directory or not raw_secret:
            return None
        try:
            directory = Path(raw_directory).expanduser().resolve()
            secret = bytes.fromhex(raw_secret)
        except (OSError, ValueError):
            return None
        if len(secret) != 32 or not directory.is_dir():
            return None
        return cls(
            directory,
            secret,
            os.environ.get(BROKER_SERVER_ID_ENV, "").strip(),
        )

    @classmethod
    def from_values(
        cls,
        *,
        directory: str | Path,
        secret_hex: str,
        server_id: str,
    ) -> "LocalPermissionBrokerClient":
        resolved = Path(directory).expanduser().resolve()
        try:
            secret = bytes.fromhex(secret_hex.strip())
        except ValueError as exc:
            raise ValueError("permission broker secret must be hex encoded") from exc
        if len(secret) != 32:
            raise ValueError("permission broker secret must contain exactly 32 bytes")
        if not resolved.is_dir():
            raise ValueError(f"permission broker directory is not available: {resolved}")
        return cls(resolved, secret, server_id.strip())

    def host_status(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        supervisor = self._read_signed_file(
            self.directory / HOST_SUPERVISOR_FILE,
            kind=HOST_SUPERVISOR_KIND,
        )
        health = self._host_health()
        supervisor_age_ms: int | None = None
        if supervisor is not None:
            updated = int(supervisor.get("updated_at_ms") or 0)
            supervisor_age_ms = max(0, now_ms - updated) if updated > 0 else None
        supervisor_ready = (
            supervisor is not None
            and supervisor_age_ms is not None
            and supervisor_age_ms <= 1_000
        )
        if not supervisor_ready:
            state = "disconnected"
        elif bool(supervisor.get("circuit_open")):
            state = "disconnected"
        elif health is None:
            state = "degraded" if bool(supervisor.get("worker_alive")) else "disconnected"
        else:
            state = str(supervisor.get("state") or "ready")
            if state not in {"connecting", "ready", "degraded", "restarting"}:
                state = "ready"
        heartbeat_at_ms = int(health.get("updated_at_ms") or 0) if health else None
        heartbeat_age_ms = (
            max(0, now_ms - heartbeat_at_ms)
            if isinstance(heartbeat_at_ms, int) and heartbeat_at_ms > 0
            else None
        )
        generation = (
            str(health.get("generation") or "")
            if health is not None
            else str((supervisor or {}).get("generation") or "")
        )
        return {
            "contract_version": 2,
            "supported": True,
            "configured": True,
            "connection": {
                "state": state,
                "host_instance_id": str((supervisor or {}).get("host_instance_id") or ""),
                "generation": generation or None,
                "generation_index": (supervisor or {}).get("generation_index"),
                "worker_pid": (supervisor or {}).get("worker_pid"),
                "worker_alive": bool((supervisor or {}).get("worker_alive", False)),
                "last_seen_ms": heartbeat_at_ms,
                "heartbeat_age_ms": heartbeat_age_ms,
                "supervisor_age_ms": supervisor_age_ms,
                "restart_count": int((supervisor or {}).get("restart_count") or 0),
                "circuit_open": bool((supervisor or {}).get("circuit_open", False)),
            },
            "invocation": {
                "state": "ready" if state == "ready" else "unavailable" if state == "disconnected" else "unknown",
                "reasons": [] if state == "ready" else [{"code": f"HOST_{state.upper()}"}],
            },
            "health_revision": hashlib.sha256(
                f"{state}:{generation}:{heartbeat_at_ms}:{(supervisor or {}).get('restart_count', 0)}".encode("utf-8")
            ).hexdigest()[:16],
            "ok": True,
        }

    def host_reconnect(self) -> dict[str, Any]:
        self._last_health_marker = None
        self._last_health_seen_monotonic = 0.0
        status = self.host_status()
        status["reconnected"] = status["connection"]["state"] == "ready"
        return status

    def host_diagnostics(self, *, max_events: int = 20) -> dict[str, Any]:
        limit = max(1, min(int(max_events), 50))
        errors: list[dict[str, str]] = []
        try:
            supervisor = self._read_signed_file(
                self.directory / HOST_SUPERVISOR_FILE,
                kind=HOST_SUPERVISOR_KIND,
            ) or {}
        except Exception as exc:
            supervisor = {}
            errors.append({"source": "supervisor", "error": type(exc).__name__})
        try:
            worker = self._read_signed_file(
                self.directory / HOST_DIAGNOSTICS_FILE,
                kind=HOST_DIAGNOSTICS_KIND,
            ) or {}
        except Exception as exc:
            worker = {}
            errors.append({"source": "worker", "error": type(exc).__name__})
        try:
            status = self.host_status()
        except Exception as exc:
            status = {
                "contract_version": 2,
                "supported": True,
                "configured": True,
                "connection": {"state": "degraded"},
                "invocation": {"state": "unknown", "reasons": [{"code": "HOST_DIAGNOSTICS_PARTIAL"}]},
                "ok": True,
            }
            errors.append({"source": "status", "error": type(exc).__name__})
        supervisor_events = supervisor.get("events")
        worker_events = worker.get("events")
        providers = worker.get("providers")
        active = worker.get("active")
        return {
            "status": status,
            "supervisor": {
                key: supervisor.get(key)
                for key in (
                    "host_instance_id", "state", "generation", "generation_index",
                    "supervisor_pid", "worker_pid", "worker_alive", "restart_count",
                    "circuit_open", "heartbeat_at_ms", "updated_at_ms",
                )
            },
            "providers": list(providers) if isinstance(providers, list) else [],
            "active": (list(active)[:16] if isinstance(active, list) else []),
            "events": (
                (list(supervisor_events)[-limit:] if isinstance(supervisor_events, list) else [])
                + (list(worker_events)[-limit:] if isinstance(worker_events, list) else [])
            )[-limit:],
            "partial": bool(errors),
            "errors": errors,
            "ok": True,
        }

    def host_restart(self, *, timeout_seconds: int = 5) -> dict[str, Any]:
        timeout = max(1, min(int(timeout_seconds), 10))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-control.request.json"
        response_path = self.directory / f"{request_id}.host-control.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CONTROL_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "runtime_instance_id": self.runtime_instance_id,
            "action": "restart",
            "created_at": now,
            "expires_at": now + timeout,
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return {
                "ok": False,
                "error": "无法创建 Host restart 请求。",
                "cause_code": "HOST_REQUEST_WRITE_FAILED",
                "request_id": request_id,
            }
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                raw = self._read_signed_file(response_path, kind=HOST_CONTROL_KIND)
                if raw is None:
                    time.sleep(0.05)
                    continue
                if raw.get("request_id") != request_id or raw.get("action") != "restart":
                    return {
                        "ok": False,
                        "error": "Host restart 响应与请求不匹配。",
                        "cause_code": "HOST_PROTOCOL_MISMATCH",
                        "request_id": request_id,
                    }
                self._last_health_marker = None
                return {
                    "ok": bool(raw.get("ok")),
                    "request_id": request_id,
                    "host_instance_id": raw.get("host_instance_id"),
                    "generation": raw.get("generation"),
                    "generation_index": raw.get("generation_index"),
                    "error": str(raw.get("error") or ""),
                }
            return {
                "ok": False,
                "error": "Host restart 响应超时。",
                "cause_code": "HOST_CONTROL_TIMEOUT",
                "request_id": request_id,
            }
        finally:
            for target in (request_path, response_path):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

    def resolve_host_tool(
        self,
        program: str,
        *,
        workspace: str | Path | None = None,
        timeout_seconds: int = HOST_TOOL_RESOLUTION_TTL_SECONDS,
    ) -> LocalHostToolResolution:
        from .toolchains.registration import normalize_program_name

        normalized = normalize_program_name(program)
        health = self._host_health()
        if health is None:
            return LocalHostToolResolution(
                "unavailable",
                error="Workbench Host 工具服务当前不可用。",
                details={"stage": "preflight", "cause_code": "HOST_HEALTH_STALE"},
            )
        generation = str(health["generation"])
        timeout = max(1, min(int(timeout_seconds), HOST_TOOL_RESOLUTION_TTL_SECONDS))
        now = int(time.time())
        queued_at_ms = int(time.time() * 1000)
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-tool.request.json"
        ack_path = self.directory / f"{request_id}.host-tool.ack.json"
        response_path = self.directory / f"{request_id}.host-tool.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_TOOL_RESOLUTION_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "program": normalized,
            "workspace": str(Path(workspace).expanduser().resolve()) if workspace else "",
            "generation": generation,
            "runtime_instance_id": self.runtime_instance_id,
            "queued_at_ms": queued_at_ms,
            "deadline_at_ms": queued_at_ms + timeout * 1000,
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostToolResolution(
                "unavailable",
                error="无法创建主机工具解析请求。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="queue",
                    cause_code="HOST_REQUEST_WRITE_FAILED",
                ),
            )

        deadline = time.monotonic() + timeout
        ack: dict[str, Any] | None = None
        try:
            ack, immediate_response, ack_error = self._await_host_ack(
                request_id=request_id,
                request_kind=HOST_TOOL_RESOLUTION_KIND,
                generation=generation,
                ack_path=ack_path,
                response_path=response_path,
            )
            if ack_error is not None:
                cause_code = str(ack_error.get("cause_code") or "HOST_ACK_TIMEOUT")
                return LocalHostToolResolution(
                    "ack_timeout" if cause_code == "HOST_ACK_TIMEOUT" else "unavailable",
                    error=(
                        "等待 Workbench Host 请求确认超时。"
                        if cause_code == "HOST_ACK_TIMEOUT"
                        else "Workbench Host 已断开。"
                    ),
                    details={**ack_error, "queued_at_ms": queued_at_ms},
                )
            raw = immediate_response
            while time.monotonic() < deadline:
                if raw is None:
                    raw = self._read_signed_file(response_path, kind=HOST_TOOL_RESOLUTION_KIND)
                if raw is None:
                    health = self._host_health()
                    if health is None or str(health.get("generation") or "") != generation:
                        return LocalHostToolResolution(
                            "unavailable",
                            error="Workbench Host 在执行工具发现时断开。",
                            details=self._host_request_details(
                                request_id=request_id,
                                generation=generation,
                                queued_at_ms=queued_at_ms,
                                stage="execute",
                                cause_code="HOST_DISCONNECTED",
                                ack=ack,
                            ),
                        )
                    time.sleep(0.05)
                    continue
                if (
                    raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("program") != normalized
                    or str(raw.get("workspace") or "") != str(payload["workspace"])
                    or str(raw.get("generation") or "") != generation
                ):
                    return LocalHostToolResolution(
                        "unavailable",
                        error="主机工具解析响应与请求不匹配。",
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="response",
                            cause_code="HOST_PROTOCOL_MISMATCH",
                            ack=ack,
                            response=raw,
                        ),
                    )
                if raw.get("ok") is True and isinstance(raw.get("proposal"), dict):
                    return LocalHostToolResolution(
                        "resolved",
                        proposal=dict(raw["proposal"]),
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="completed",
                            cause_code="",
                            ack=ack,
                            response=raw,
                        ),
                    )
                return LocalHostToolResolution(
                    "not_found",
                    error=str(raw.get("error") or f"当前用户环境未找到工具 {normalized}。"),
                    details=self._host_request_details(
                        request_id=request_id,
                        generation=generation,
                        queued_at_ms=queued_at_ms,
                        stage="provider",
                        cause_code=str(raw.get("cause_code") or "APP_RESOLUTION_FAILED"),
                        ack=ack,
                        response=raw,
                    ),
                )
            return LocalHostToolResolution(
                "timeout",
                error="等待 Workbench Host 解析工具路径超时。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="execute",
                    cause_code="HOST_RESPONSE_TIMEOUT",
                    ack=ack,
                ),
            )
        finally:
            for path in (request_path, ack_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def invoke_host_capability(
        self,
        capability: str,
        action: str,
        *,
        parameters: dict[str, Any] | None = None,
        session_id: str = "",
        timeout_seconds: int = HOST_CAPABILITY_TTL_SECONDS,
    ) -> LocalHostCapabilityResult:
        normalized_capability = str(capability or "").strip().lower()
        normalized_action = str(action or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", normalized_capability):
            return LocalHostCapabilityResult("invalid", error="Host Capability 名称无效。")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", normalized_action):
            return LocalHostCapabilityResult("invalid", error="Host Capability action 无效。")
        if session_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            return LocalHostCapabilityResult("invalid", error="Host Capability session_id 无效。")

        health = self._host_health()
        if health is None:
            return LocalHostCapabilityResult(
                "unavailable",
                error="Workbench Desktop Host 当前不可用。",
                details={"stage": "preflight", "cause_code": "HOST_HEALTH_STALE"},
            )
        generation = str(health["generation"])
        timeout = max(1, min(int(timeout_seconds), HOST_CAPABILITY_TTL_SECONDS))
        now = int(time.time())
        queued_at_ms = int(time.time() * 1000)
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-capability.request.json"
        ack_path = self.directory / f"{request_id}.host-capability.ack.json"
        response_path = self.directory / f"{request_id}.host-capability.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CAPABILITY_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "capability": normalized_capability,
            "action": normalized_action,
            "session_id": session_id,
            "generation": generation,
            "runtime_instance_id": self.runtime_instance_id,
            "queued_at_ms": queued_at_ms,
            "deadline_at_ms": queued_at_ms + timeout * 1000,
            "parameters": dict(parameters or {}),
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostCapabilityResult(
                "unavailable",
                error="无法创建 Host Capability 请求。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="queue",
                    cause_code="HOST_REQUEST_WRITE_FAILED",
                ),
            )

        deadline = time.monotonic() + timeout
        ack: dict[str, Any] | None = None
        try:
            ack, immediate_response, ack_error = self._await_host_ack(
                request_id=request_id,
                request_kind=HOST_CAPABILITY_KIND,
                generation=generation,
                ack_path=ack_path,
                response_path=response_path,
            )
            if ack_error is not None:
                cause_code = str(ack_error.get("cause_code") or "HOST_ACK_TIMEOUT")
                return LocalHostCapabilityResult(
                    "ack_timeout" if cause_code == "HOST_ACK_TIMEOUT" else "unavailable",
                    error=(
                        "等待 Workbench Host 请求确认超时。"
                        if cause_code == "HOST_ACK_TIMEOUT"
                        else "Workbench Desktop Host 已断开。"
                    ),
                    details={**ack_error, "queued_at_ms": queued_at_ms},
                )
            raw = immediate_response
            while time.monotonic() < deadline:
                if raw is None:
                    raw = self._read_signed_file(response_path, kind=HOST_CAPABILITY_KIND)
                if raw is None:
                    health = self._host_health()
                    if health is None:
                        return LocalHostCapabilityResult(
                            "unavailable",
                            error="Workbench Desktop Host 在执行期间断开。",
                            details=self._host_request_details(
                                request_id=request_id,
                                generation=generation,
                                queued_at_ms=queued_at_ms,
                                stage="execute",
                                cause_code="HOST_DISCONNECTED",
                                ack=ack,
                            ),
                        )
                    current_generation = str(health.get("generation") or "")
                    if current_generation != generation:
                        cause_code = (
                            "SESSION_EXPIRED"
                            if normalized_capability == "browser" and session_id
                            else "HOST_GENERATION_CHANGED"
                        )
                        return LocalHostCapabilityResult(
                            "expired" if cause_code == "SESSION_EXPIRED" else "unavailable",
                            error=(
                                "Host generation 已变化；旧 Browser Session 已过期。"
                                if cause_code == "SESSION_EXPIRED"
                                else "Host generation 已变化，请重新发起请求。"
                            ),
                            details=self._host_request_details(
                                request_id=request_id,
                                generation=generation,
                                queued_at_ms=queued_at_ms,
                                stage="execute",
                                cause_code=cause_code,
                                ack=ack,
                            ),
                        )
                    time.sleep(0.05)
                    continue
                if (
                    raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("capability") != normalized_capability
                    or raw.get("action") != normalized_action
                    or str(raw.get("session_id") or "") != session_id
                    or str(raw.get("generation") or "") != generation
                ):
                    return LocalHostCapabilityResult(
                        "unavailable",
                        error="Host Capability 响应与请求不匹配。",
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="response",
                            cause_code="HOST_PROTOCOL_MISMATCH",
                            ack=ack,
                            response=raw,
                        ),
                    )
                if raw.get("ok") is True and isinstance(raw.get("result"), dict):
                    result = dict(raw["result"])
                    result.setdefault("request_id", request_id)
                    result.setdefault("generation", generation)
                    return LocalHostCapabilityResult(
                        "ok",
                        result=result,
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="completed",
                            cause_code="",
                            ack=ack,
                            response=raw,
                        ),
                    )
                cause_code = str(raw.get("cause_code") or "HOST_CAPABILITY_FAILED")
                return LocalHostCapabilityResult(
                    "expired" if cause_code == "SESSION_EXPIRED" else "error",
                    error=str(raw.get("error") or "Host Capability 操作失败。"),
                    details=self._host_request_details(
                        request_id=request_id,
                        generation=generation,
                        queued_at_ms=queued_at_ms,
                        stage=str(raw.get("stage") or "provider"),
                        cause_code=cause_code,
                        ack=ack,
                        response=raw,
                    ),
                )
            return LocalHostCapabilityResult(
                "timeout",
                error="等待 Workbench Host Capability 响应超时。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="execute",
                    cause_code="HOST_RESPONSE_TIMEOUT",
                    ack=ack,
                ),
            )
        finally:
            for path in (request_path, ack_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def invoke_host_identity(
        self,
        action: str,
        *,
        command_id: str = "",
        parameters: dict[str, Any] | None = None,
        timeout_seconds: int = HOST_IDENTITY_TTL_SECONDS,
    ) -> LocalHostIdentityResult:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"start", "poll", "write", "kill", "read_output"}:
            return LocalHostIdentityResult("invalid", error="Host identity action 无效。")
        if normalized_action != "start" and not re.fullmatch(
            r"host_[A-Za-z0-9_-]{8,128}", command_id
        ):
            return LocalHostIdentityResult("invalid", error="Host identity command_id 无效。")

        health = self._host_health()
        if health is None:
            return LocalHostIdentityResult(
                "unavailable",
                error="Workbench Desktop Host 当前不可用。",
                details={"stage": "preflight", "cause_code": "HOST_DISCONNECTED"},
            )
        generation = str(health["generation"])
        timeout = max(1, min(int(timeout_seconds), HOST_IDENTITY_TTL_SECONDS))
        now = int(time.time())
        queued_at_ms = int(time.time() * 1000)
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-identity.request.json"
        ack_path = self.directory / f"{request_id}.host-identity.ack.json"
        response_path = self.directory / f"{request_id}.host-identity.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_IDENTITY_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "action": normalized_action,
            "command_id": command_id,
            "generation": generation,
            "runtime_instance_id": self.runtime_instance_id,
            "queued_at_ms": queued_at_ms,
            "deadline_at_ms": queued_at_ms + timeout * 1000,
            "parameters": dict(parameters or {}),
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostIdentityResult(
                "unavailable",
                error="无法创建 Host identity execution 请求。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="queue",
                    cause_code="HOST_REQUEST_WRITE_FAILED",
                ),
            )

        deadline = time.monotonic() + timeout
        ack: dict[str, Any] | None = None
        try:
            ack, immediate_response, ack_error = self._await_host_ack(
                request_id=request_id,
                request_kind=HOST_IDENTITY_KIND,
                generation=generation,
                ack_path=ack_path,
                response_path=response_path,
            )
            if ack_error is not None:
                cause_code = str(ack_error.get("cause_code") or "HOST_ACK_TIMEOUT")
                return LocalHostIdentityResult(
                    "ack_timeout" if cause_code == "HOST_ACK_TIMEOUT" else "unavailable",
                    error=(
                        "等待 Workbench Host 请求确认超时。"
                        if cause_code == "HOST_ACK_TIMEOUT"
                        else "Workbench Desktop Host 已断开。"
                    ),
                    details={**ack_error, "queued_at_ms": queued_at_ms},
                )
            raw = immediate_response
            while time.monotonic() < deadline:
                if raw is None:
                    raw = self._read_signed_file(response_path, kind=HOST_IDENTITY_KIND)
                if raw is None:
                    current = self._host_health()
                    if current is None:
                        return LocalHostIdentityResult(
                            "unavailable",
                            error="Workbench Desktop Host 在执行期间断开。",
                            details=self._host_request_details(
                                request_id=request_id,
                                generation=generation,
                                queued_at_ms=queued_at_ms,
                                stage="execute",
                                cause_code="HOST_DISCONNECTED",
                                ack=ack,
                            ),
                        )
                    if str(current.get("generation") or "") != generation:
                        return LocalHostIdentityResult(
                            "unavailable",
                            error="Host generation 已变化；旧 Host Identity command 不再有效。",
                            details=self._host_request_details(
                                request_id=request_id,
                                generation=generation,
                                queued_at_ms=queued_at_ms,
                                stage="execute",
                                cause_code="HOST_GENERATION_CHANGED",
                                ack=ack,
                            ),
                        )
                    time.sleep(0.05)
                    continue
                if (
                    raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("action") != normalized_action
                    or str(raw.get("command_id") or "") != command_id
                    or str(raw.get("generation") or "") != generation
                ):
                    return LocalHostIdentityResult(
                        "unavailable",
                        error="Host identity execution 响应与请求不匹配。",
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="response",
                            cause_code="HOST_PROTOCOL_MISMATCH",
                            ack=ack,
                            response=raw,
                        ),
                    )
                if raw.get("ok") is True and isinstance(raw.get("result"), dict):
                    result = dict(raw["result"])
                    result.setdefault("request_id", request_id)
                    result.setdefault("generation", generation)
                    return LocalHostIdentityResult(
                        "ok",
                        result=result,
                        details=self._host_request_details(
                            request_id=request_id,
                            generation=generation,
                            queued_at_ms=queued_at_ms,
                            stage="completed",
                            cause_code="",
                            ack=ack,
                            response=raw,
                        ),
                    )
                return LocalHostIdentityResult(
                    "error",
                    error=str(raw.get("error") or "Host identity execution 操作失败。"),
                    details=self._host_request_details(
                        request_id=request_id,
                        generation=generation,
                        queued_at_ms=queued_at_ms,
                        stage=str(raw.get("stage") or "provider"),
                        cause_code=str(raw.get("cause_code") or "HOST_IDENTITY_FAILED"),
                        ack=ack,
                        response=raw,
                    ),
                )
            return LocalHostIdentityResult(
                "timeout",
                error="等待 Workbench Host identity execution 响应超时。",
                details=self._host_request_details(
                    request_id=request_id,
                    generation=generation,
                    queued_at_ms=queued_at_ms,
                    stage="execute",
                    cause_code="HOST_RESPONSE_TIMEOUT",
                    ack=ack,
                ),
            )
        finally:
            for path in (request_path, ack_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def request(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        display_arguments: dict[str, Any] | None = None,
        permission: str,
        reason: str,
        principal: str,
        timeout_seconds: int = BROKER_REQUEST_TTL_SECONDS,
    ) -> LocalPermissionDecision:
        timeout = max(1, min(int(timeout_seconds), BROKER_REQUEST_TTL_SECONDS))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.request.json"
        response_path = self.directory / f"{request_id}.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "request_id": request_id,
            "server_id": self.server_id,
            "tool_name": tool_name,
            "permission": permission,
            "reason": str(reason)[:1200],
            "arguments": redact_for_display(display_arguments or arguments),
            "arguments_hash": hashlib.sha256(canonical_payload({"arguments": arguments})).hexdigest(),
            "principal_hash": hashlib.sha256((principal or "anonymous").encode("utf-8")).hexdigest(),
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalPermissionDecision("unavailable")

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    time.sleep(0.1)
                    continue
                except (OSError, json.JSONDecodeError):
                    return LocalPermissionDecision("unavailable")
                if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                    return LocalPermissionDecision("unavailable")
                if raw.get("request_id") != request_id:
                    return LocalPermissionDecision("unavailable")
                if permission == "toolchain_registration" and (
                    raw.get("server_id") != self.server_id
                    or raw.get("arguments_hash") != payload["arguments_hash"]
                    or raw.get("permission") != permission
                ):
                    return LocalPermissionDecision("unavailable")
                approved = raw.get("approved") is True
                raw_scope = str(raw.get("scope") or "once")
                scope = (
                    raw_scope
                    if raw_scope in {"session", "resource_session", "remember_resource"}
                    else "once"
                )
                if permission == "toolchain_registration" and raw.get("scope") == "remember":
                    scope = "remember"
                    if approved and not isinstance(raw.get("registration"), dict):
                        return LocalPermissionDecision("unavailable")
                return LocalPermissionDecision(
                    "approved" if approved else "denied",
                    scope=scope if approved else "once",
                    registration=(raw.get("registration") if approved
                                  and permission == "toolchain_registration"
                                  and raw.get("scope") == "remember" else None),
                )
            return LocalPermissionDecision("timeout")
        finally:
            for path in (request_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass


class LocalWorkflowApprovalBrokerClient:
    """Non-blocking signed IPC client for human Workflow approvals.

    The channel deliberately reuses the Desktop permission broker's private
    directory and HMAC secret, while keeping a distinct payload kind and file
    suffix. Workspace tools therefore cannot forge an approval by editing a
    Workflow Run JSON file.
    """

    def __init__(self, directory: Path, secret: bytes, server_id: str) -> None:
        self.directory = directory.resolve()
        self.secret = secret
        self.server_id = server_id.strip()

    @classmethod
    def from_env(cls) -> "LocalWorkflowApprovalBrokerClient | None":
        raw_directory = os.environ.get(BROKER_DIR_ENV, "").strip()
        raw_secret = os.environ.get(BROKER_SECRET_ENV, "").strip()
        if not raw_directory or not raw_secret:
            return None
        try:
            directory = Path(raw_directory).expanduser().resolve()
            secret = bytes.fromhex(raw_secret)
        except (OSError, ValueError):
            return None
        if len(secret) != 32 or not directory.is_dir():
            return None
        return cls(
            directory,
            secret,
            os.environ.get(BROKER_SERVER_ID_ENV, "").strip(),
        )

    @classmethod
    def from_values(
        cls,
        *,
        directory: str | Path,
        secret_hex: str,
        server_id: str,
    ) -> "LocalWorkflowApprovalBrokerClient":
        resolved = Path(directory).expanduser().resolve()
        try:
            secret = bytes.fromhex(secret_hex.strip())
        except ValueError as exc:
            raise ValueError("workflow approval broker secret must be hex encoded") from exc
        if len(secret) != 32:
            raise ValueError("workflow approval broker secret must contain exactly 32 bytes")
        if not resolved.is_dir():
            raise ValueError(f"workflow approval broker directory is not available: {resolved}")
        return cls(resolved, secret, server_id)

    @staticmethod
    def _safe_id(value: str, *, label: str) -> str:
        normalized = value.strip()
        if not normalized or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in normalized
        ):
            raise ValueError(f"invalid workflow approval {label}: {value!r}")
        return normalized

    def _request_path(self, request_id: str) -> Path:
        return self.directory / f"{request_id}.workflow-approval.request.json"

    def _response_path(self, request_id: str) -> Path:
        return self.directory / f"{request_id}.workflow-approval.response.json"

    def publish(
        self,
        *,
        run_id: str,
        node_id: str,
        approval_id: str,
        title: str,
        description: str,
        timeout_seconds: int = WORKFLOW_APPROVAL_TTL_SECONDS,
    ) -> str:
        run_id = self._safe_id(run_id, label="run_id")
        node_id = self._safe_id(node_id, label="node_id")
        approval_id = self._safe_id(approval_id, label="approval_id")
        timeout = max(60, min(int(timeout_seconds), WORKFLOW_APPROVAL_TTL_SECONDS))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": WORKFLOW_APPROVAL_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "run_id": run_id,
            "node_id": node_id,
            "approval_id": approval_id,
            "title": str(title)[:400],
            "description": str(description)[:1200],
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        atomic_json_write(self._request_path(request_id), payload)
        return request_id

    def request_is_current(
        self,
        request_id: str,
        *,
        run_id: str,
        node_id: str,
        approval_id: str,
    ) -> bool:
        try:
            request_id = self._safe_id(request_id, label="request_id")
            raw = json.loads(self._request_path(request_id).read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(raw, dict)
            and verify_payload(self.secret, raw)
            and raw.get("version") == BROKER_VERSION
            and raw.get("kind") == WORKFLOW_APPROVAL_KIND
            and raw.get("server_id") == self.server_id
            and raw.get("request_id") == request_id
            and raw.get("run_id") == run_id
            and raw.get("node_id") == node_id
            and raw.get("approval_id") == approval_id
            and int(raw.get("expires_at", 0)) > int(time.time())
        )

    def consume_response(
        self,
        request_id: str,
        *,
        run_id: str,
        node_id: str,
        approval_id: str,
    ) -> bool | None:
        request_id = self._safe_id(request_id, label="request_id")
        response_path = self._response_path(request_id)
        try:
            raw = json.loads(response_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Workflow approval response 无法读取") from exc

        valid = bool(
            isinstance(raw, dict)
            and verify_payload(self.secret, raw)
            and raw.get("version") == BROKER_VERSION
            and raw.get("kind") == WORKFLOW_APPROVAL_KIND
            and raw.get("server_id") == self.server_id
            and raw.get("request_id") == request_id
            and raw.get("run_id") == run_id
            and raw.get("node_id") == node_id
            and raw.get("approval_id") == approval_id
            and isinstance(raw.get("approved"), bool)
        )
        if not valid:
            raise RuntimeError("Workflow approval response 签名或绑定信息无效")
        approved = raw["approved"] is True
        for path in (self._request_path(request_id), response_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return approved

