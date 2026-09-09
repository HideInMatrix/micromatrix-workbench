from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
    BROKER_VERSION,
    HOST_CAPABILITY_KIND,
    HOST_CREDENTIAL_KIND,
    HOST_TOOL_RESOLUTION_KIND,
    WORKFLOW_APPROVAL_KIND,
    atomic_json_write,
    sign_payload,
    verify_payload,
)
from agent_runtime.toolchains.registration import fingerprint, prepare_toolchain
from agent_workbench.host_capabilities import HostCapabilityError, HostCapabilityManager
from agent_workbench.host_credentials import HostCredentialError, HostCredentialManager

from .host_tools import resolve_host_tool


class DesktopPermissionBroker:
    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="micromatrix-workbench-permissions-"))
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        self.secret = secrets.token_bytes(32)
        self.host_capabilities = HostCapabilityManager()
        self.host_credentials = HostCredentialManager(self.directory / "host-credentials")
        self._host_tool_stop = threading.Event()
        self._host_tool_worker = threading.Thread(
            target=self._host_tool_loop,
            name="micromatrix-host-tool-resolver",
            daemon=True,
        )
        self._host_tool_worker.start()

    def _host_tool_loop(self) -> None:
        while not self._host_tool_stop.wait(0.05):
            for path in tuple(self.directory.glob("*.host-tool.request.json")):
                self._respond_host_tool_request(path)
            for path in tuple(self.directory.glob("*.host-capability.request.json")):
                self._respond_host_capability_request(path)
            for path in tuple(self.directory.glob("*.host-credential.request.json")):
                self._respond_host_credential_request(path)
            self.host_credentials.cleanup_expired()

    def _respond_host_credential_request(self, path: Path) -> None:
        request_id = path.name.removesuffix(".host-credential.request.json")
        response_path = self.directory / f"{request_id}.host-credential.response.json"
        if response_path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != HOST_CREDENTIAL_KIND
            or str(raw.get("request_id") or "") != request_id
        ):
            return
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            try:
                path.unlink()
            except OSError:
                pass
            return
        server_id = str(raw.get("server_id") or "")
        action = str(raw.get("action") or "")
        try:
            if action == "prepare":
                result = self.host_credentials.prepare(
                    str(raw.get("service") or ""),
                    str(raw.get("operation") or ""),
                    server_id=server_id,
                    target_url=str(raw.get("target_url") or ""),
                    workspace=str(raw.get("workspace") or ""),
                    ttl_seconds=int(raw.get("ttl_seconds") or 120),
                )
            elif action == "release":
                released = self.host_credentials.release(
                    server_id,
                    str(raw.get("session_id") or ""),
                )
                result = {"released": released}
            else:
                raise HostCredentialError(f"不支持 Host Credential action: {action}")
            ok = True
            error = ""
        except (HostCredentialError, OSError, RuntimeError, ValueError) as exc:
            result = None
            ok = False
            error = str(exc)
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CREDENTIAL_KIND,
            "request_id": request_id,
            "server_id": server_id,
            "action": action,
            "ok": ok,
            "result": result,
            "error": error,
            "responded_at": int(time.time()),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(response_path, payload)
        except OSError:
            pass

    def _respond_host_capability_request(self, path: Path) -> None:
        request_id = path.name.removesuffix(".host-capability.request.json")
        response_path = self.directory / f"{request_id}.host-capability.response.json"
        if response_path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != HOST_CAPABILITY_KIND
            or str(raw.get("request_id") or "") != request_id
        ):
            return
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            try:
                path.unlink()
            except OSError:
                pass
            return
        server_id = str(raw.get("server_id") or "")
        capability = str(raw.get("capability") or "")
        action = str(raw.get("action") or "")
        session_id = str(raw.get("session_id") or "")
        parameters = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
        try:
            result = self.host_capabilities.invoke(
                capability,
                action,
                server_id=server_id,
                session_id=session_id,
                parameters=parameters,
            )
            ok = True
            error = ""
        except (HostCapabilityError, OSError, RuntimeError, ValueError) as exc:
            result = None
            ok = False
            error = str(exc)
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CAPABILITY_KIND,
            "request_id": request_id,
            "server_id": server_id,
            "capability": capability,
            "action": action,
            "session_id": session_id,
            "ok": ok,
            "result": result,
            "error": error,
            "responded_at": int(time.time()),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(response_path, payload)
        except OSError:
            pass

    def _respond_host_tool_request(self, path: Path) -> None:
        request_id = path.name.removesuffix(".host-tool.request.json")
        response_path = self.directory / f"{request_id}.host-tool.response.json"
        if response_path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != HOST_TOOL_RESOLUTION_KIND
            or str(raw.get("request_id") or "") != request_id
        ):
            return
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            try:
                path.unlink()
            except OSError:
                pass
            return
        program = str(raw.get("program") or "")
        workspace = str(raw.get("workspace") or "")
        try:
            resolution = resolve_host_tool(program, workspace=workspace or None)
            proposal = prepare_toolchain(
                program,
                str(resolution["executable"]),
                [],
            )
            proposal["resolution"] = {
                "source": "host_command",
                "resolver": resolution.get("resolver"),
                "shell": resolution.get("shell"),
                "shell_mode": resolution.get("shell_mode"),
                "shell_startup_files_evaluated": resolution.get(
                    "shell_startup_files_evaluated",
                    False,
                ),
                "workspace": resolution.get("workspace", workspace),
                "host_environment_exposed_to_ai": False,
            }
            proposal["proposal_fingerprint"] = fingerprint(
                str(proposal["executable"]),
                list(proposal["read_roots"]),
            )
            ok = True
            error = ""
        except (OSError, RuntimeError, ValueError) as exc:
            proposal = None
            ok = False
            error = str(exc)
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_TOOL_RESOLUTION_KIND,
            "request_id": request_id,
            "server_id": str(raw.get("server_id") or ""),
            "program": program,
            "workspace": workspace,
            "ok": ok,
            "proposal": proposal,
            "error": error,
            "responded_at": int(time.time()),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(response_path, payload)
        except OSError:
            pass

    def child_environment(self, server_id: str) -> dict[str, str]:
        return {
            BROKER_DIR_ENV: str(self.directory),
            BROKER_SECRET_ENV: self.secret.hex(),
            BROKER_SERVER_ID_ENV: server_id,
        }

    def pending(self) -> list[dict[str, Any]]:
        now = int(time.time())
        result: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.request.json")):
            response_path = path.with_name(
                path.name.removesuffix(".request.json") + ".response.json"
            )
            if response_path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") in {
                WORKFLOW_APPROVAL_KIND,
                HOST_TOOL_RESOLUTION_KIND,
                HOST_CAPABILITY_KIND,
                HOST_CREDENTIAL_KIND,
            }:
                continue
            if raw.get("version") != BROKER_VERSION:
                continue
            expires_at = int(raw.get("expires_at", 0))
            if expires_at <= now:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            result.append(
                {
                    "request_id": str(raw.get("request_id") or ""),
                    "server_id": str(raw.get("server_id") or ""),
                    "tool_name": str(raw.get("tool_name") or ""),
                    "permission": str(raw.get("permission") or ""),
                    "reason": str(raw.get("reason") or ""),
                    "arguments": raw.get("arguments") if isinstance(raw.get("arguments"), (dict, list)) else {},
                    "created_at": int(raw.get("created_at", 0)),
                    "expires_at": expires_at,
                }
            )
        return result

    def pending_workflow_approvals(self) -> list[dict[str, Any]]:
        now = int(time.time())
        result: list[dict[str, Any]] = []
        suffix = ".workflow-approval.request.json"
        for path in sorted(self.directory.glob(f"*{suffix}")):
            response_path = path.with_name(
                path.name.removesuffix(suffix)
                + ".workflow-approval.response.json"
            )
            if response_path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("version") != BROKER_VERSION:
                continue
            if raw.get("kind") != WORKFLOW_APPROVAL_KIND:
                continue
            expires_at = int(raw.get("expires_at", 0))
            if expires_at <= now:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            result.append(
                {
                    "request_id": str(raw.get("request_id") or ""),
                    "server_id": str(raw.get("server_id") or ""),
                    "run_id": str(raw.get("run_id") or ""),
                    "node_id": str(raw.get("node_id") or ""),
                    "approval_id": str(raw.get("approval_id") or ""),
                    "title": str(raw.get("title") or ""),
                    "description": str(raw.get("description") or ""),
                    "created_at": int(raw.get("created_at", 0)),
                    "expires_at": expires_at,
                }
            )
        return result

    def respond(self, request_id: str, decision: str | bool, *, registration: dict | None = None) -> bool:
        if not request_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in request_id):
            return False
        if isinstance(decision, bool):
            normalized_decision = "once" if decision else "deny"
        else:
            normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"deny", "once", "session", "remember"}:
            return False
        request_path = self.directory / f"{request_id}.request.json"
        response_path = self.directory / f"{request_id}.response.json"
        try:
            raw = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
            return False
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            return False
        is_registration = raw.get("permission") == "toolchain_registration"
        is_credential = raw.get("permission") == "credential_use"
        if is_registration:
            if normalized_decision not in {"deny", "remember"}:
                return False
            if normalized_decision == "remember" and not registration:
                return False
        elif is_credential and normalized_decision == "session":
            return False
        elif normalized_decision == "remember" or registration is not None:
            return False
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "request_id": request_id,
            "server_id": raw.get("server_id"),
            "arguments_hash": raw.get("arguments_hash"),
            "permission": raw.get("permission"),
            "registration": registration,
            "approved": normalized_decision != "deny",
            "scope": normalized_decision if normalized_decision in {"session", "remember"} else "once",
            "responded_at": int(time.time()),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(response_path, payload)
        except OSError:
            return False
        return True

    def respond_workflow_approval(self, request_id: str, approved: bool) -> bool:
        if not request_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in request_id
        ):
            return False
        request_path = self.directory / f"{request_id}.workflow-approval.request.json"
        response_path = self.directory / f"{request_id}.workflow-approval.response.json"
        try:
            raw = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
            return False
        if raw.get("version") != BROKER_VERSION or raw.get("kind") != WORKFLOW_APPROVAL_KIND:
            return False
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            return False
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": WORKFLOW_APPROVAL_KIND,
            "request_id": request_id,
            "server_id": str(raw.get("server_id") or ""),
            "run_id": str(raw.get("run_id") or ""),
            "node_id": str(raw.get("node_id") or ""),
            "approval_id": str(raw.get("approval_id") or ""),
            "approved": bool(approved),
            "responded_at": int(time.time()),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(response_path, payload)
        except OSError:
            return False
        return True

    def clear_server(self, server_id: str) -> None:
        for path in self.directory.glob("*.request.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") in {
                WORKFLOW_APPROVAL_KIND,
                HOST_TOOL_RESOLUTION_KIND,
                HOST_CAPABILITY_KIND,
                HOST_CREDENTIAL_KIND,
            }:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

        suffix = ".workflow-approval.request.json"
        for path in self.directory.glob(f"*{suffix}"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") != WORKFLOW_APPROVAL_KIND:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.workflow-approval.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

        host_suffix = ".host-tool.request.json"
        for path in self.directory.glob(f"*{host_suffix}"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") != HOST_TOOL_RESOLUTION_KIND:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.host-tool.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

        capability_suffix = ".host-capability.request.json"
        for path in self.directory.glob(f"*{capability_suffix}"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") != HOST_CAPABILITY_KIND:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.host-capability.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        credential_suffix = ".host-credential.request.json"
        for path in self.directory.glob(f"*{credential_suffix}"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") != HOST_CREDENTIAL_KIND:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.host-credential.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        self.host_capabilities.close_server(server_id)
        self.host_credentials.close_server(server_id)

    def cleanup(self) -> None:
        self._host_tool_stop.set()
        self._host_tool_worker.join(timeout=1)
        self.host_capabilities.close()
        self.host_credentials.close()
        shutil.rmtree(self.directory, ignore_errors=True)

