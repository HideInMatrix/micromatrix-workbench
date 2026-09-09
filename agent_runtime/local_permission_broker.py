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
HOST_CREDENTIAL_TTL_SECONDS = 30
WORKFLOW_APPROVAL_TTL_SECONDS = 86_400
WORKFLOW_APPROVAL_KIND = "workflow_approval"
HOST_TOOL_RESOLUTION_KIND = "host_tool_resolution"
HOST_CAPABILITY_KIND = "host_capability"
HOST_CREDENTIAL_KIND = "host_credential"
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


@dataclass(frozen=True, slots=True)
class LocalHostCapabilityResult:
    status: str
    result: dict[str, Any] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True, slots=True)
class LocalHostCredentialResult:
    status: str
    result: dict[str, Any] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class LocalPermissionBrokerClient:
    def __init__(self, directory: Path, secret: bytes, server_id: str) -> None:
        self.directory = directory.resolve()
        self.secret = secret
        self.server_id = server_id

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

    def resolve_host_tool(
        self,
        program: str,
        *,
        workspace: str | Path | None = None,
        timeout_seconds: int = HOST_TOOL_RESOLUTION_TTL_SECONDS,
    ) -> LocalHostToolResolution:
        from .toolchains.registration import normalize_program_name

        normalized = normalize_program_name(program)
        timeout = max(1, min(int(timeout_seconds), HOST_TOOL_RESOLUTION_TTL_SECONDS))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-tool.request.json"
        response_path = self.directory / f"{request_id}.host-tool.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_TOOL_RESOLUTION_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "program": normalized,
            "workspace": str(Path(workspace).expanduser().resolve()) if workspace else "",
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostToolResolution("unavailable", error="无法创建主机工具解析请求。")

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                except (OSError, json.JSONDecodeError):
                    return LocalHostToolResolution("unavailable", error="主机工具解析响应不可读。")
                if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                    return LocalHostToolResolution("unavailable", error="主机工具解析响应签名无效。")
                if (
                    raw.get("version") != BROKER_VERSION
                    or raw.get("kind") != HOST_TOOL_RESOLUTION_KIND
                    or raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("program") != normalized
                    or str(raw.get("workspace") or "") != str(payload["workspace"])
                ):
                    return LocalHostToolResolution("unavailable", error="主机工具解析响应与请求不匹配。")
                if raw.get("ok") is True and isinstance(raw.get("proposal"), dict):
                    return LocalHostToolResolution("resolved", proposal=dict(raw["proposal"]))
                return LocalHostToolResolution(
                    "not_found",
                    error=str(raw.get("error") or f"当前用户环境未找到工具 {normalized}。"),
                )
            return LocalHostToolResolution("timeout", error="等待 Workbench Host 解析工具路径超时。")
        finally:
            for path in (request_path, response_path):
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

        timeout = max(1, min(int(timeout_seconds), HOST_CAPABILITY_TTL_SECONDS))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-capability.request.json"
        response_path = self.directory / f"{request_id}.host-capability.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CAPABILITY_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "capability": normalized_capability,
            "action": normalized_action,
            "session_id": session_id,
            "parameters": dict(parameters or {}),
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostCapabilityResult("unavailable", error="无法创建 Host Capability 请求。")

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                except (OSError, json.JSONDecodeError):
                    return LocalHostCapabilityResult("unavailable", error="Host Capability 响应不可读。")
                if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                    return LocalHostCapabilityResult("unavailable", error="Host Capability 响应签名无效。")
                if (
                    raw.get("version") != BROKER_VERSION
                    or raw.get("kind") != HOST_CAPABILITY_KIND
                    or raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("capability") != normalized_capability
                    or raw.get("action") != normalized_action
                    or str(raw.get("session_id") or "") != session_id
                ):
                    return LocalHostCapabilityResult("unavailable", error="Host Capability 响应与请求不匹配。")
                if raw.get("ok") is True and isinstance(raw.get("result"), dict):
                    return LocalHostCapabilityResult("ok", result=dict(raw["result"]))
                return LocalHostCapabilityResult(
                    "error",
                    error=str(raw.get("error") or "Host Capability 操作失败。"),
                )
            return LocalHostCapabilityResult("timeout", error="等待 Workbench Host Capability 响应超时。")
        finally:
            for path in (request_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def prepare_host_credential(
        self,
        service: str,
        operation: str,
        *,
        target_url: str,
        workspace: str | Path,
        ttl_seconds: int = 120,
        timeout_seconds: int = HOST_CREDENTIAL_TTL_SECONDS,
    ) -> LocalHostCredentialResult:
        return self._host_credential_request(
            "prepare",
            service=service,
            operation=operation,
            target_url=target_url,
            workspace=str(Path(workspace).expanduser().resolve()),
            ttl_seconds=max(15, min(int(ttl_seconds), 660)),
            timeout_seconds=timeout_seconds,
        )

    def release_host_credential(
        self,
        session_id: str,
        *,
        timeout_seconds: int = HOST_CREDENTIAL_TTL_SECONDS,
    ) -> LocalHostCredentialResult:
        return self._host_credential_request(
            "release",
            session_id=session_id,
            timeout_seconds=timeout_seconds,
        )

    def _host_credential_request(
        self,
        action: str,
        *,
        service: str = "",
        operation: str = "",
        target_url: str = "",
        workspace: str = "",
        session_id: str = "",
        ttl_seconds: int = 120,
        timeout_seconds: int = HOST_CREDENTIAL_TTL_SECONDS,
    ) -> LocalHostCredentialResult:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"prepare", "release"}:
            return LocalHostCredentialResult("invalid", error="Host Credential action 无效。")
        if normalized_action == "release" and not re.fullmatch(
            r"[A-Za-z0-9_-]{8,128}", session_id
        ):
            return LocalHostCredentialResult("invalid", error="Host Credential session_id 无效。")

        timeout = max(1, min(int(timeout_seconds), HOST_CREDENTIAL_TTL_SECONDS))
        now = int(time.time())
        request_id = secrets.token_urlsafe(24)
        request_path = self.directory / f"{request_id}.host-credential.request.json"
        response_path = self.directory / f"{request_id}.host-credential.response.json"
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CREDENTIAL_KIND,
            "request_id": request_id,
            "server_id": self.server_id,
            "action": normalized_action,
            "service": str(service or "").strip().lower(),
            "operation": str(operation or "").strip().lower(),
            "target_url": str(target_url or ""),
            "workspace": workspace,
            "session_id": session_id,
            "ttl_seconds": max(15, min(int(ttl_seconds), 660)),
            "created_at": now,
            "expires_at": now + timeout,
            "pid": os.getpid(),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return LocalHostCredentialResult(
                "unavailable", error="无法创建 Host Credential 请求。"
            )

        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                except (OSError, json.JSONDecodeError):
                    return LocalHostCredentialResult(
                        "unavailable", error="Host Credential 响应不可读。"
                    )
                if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                    return LocalHostCredentialResult(
                        "unavailable", error="Host Credential 响应签名无效。"
                    )
                if (
                    raw.get("version") != BROKER_VERSION
                    or raw.get("kind") != HOST_CREDENTIAL_KIND
                    or raw.get("request_id") != request_id
                    or raw.get("server_id") != self.server_id
                    or raw.get("action") != normalized_action
                ):
                    return LocalHostCredentialResult(
                        "unavailable", error="Host Credential 响应与请求不匹配。"
                    )
                if raw.get("ok") is True and isinstance(raw.get("result"), dict):
                    return LocalHostCredentialResult("ok", result=dict(raw["result"]))
                return LocalHostCredentialResult(
                    "error",
                    error=str(raw.get("error") or "Host Credential 操作失败。"),
                )
            return LocalHostCredentialResult(
                "timeout", error="等待 Workbench Host Credential 响应超时。"
            )
        finally:
            for path in (request_path, response_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def request(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
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
            "arguments": redact_for_display(arguments),
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
                scope = "session" if raw.get("scope") == "session" else "once"
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

