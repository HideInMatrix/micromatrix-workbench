from __future__ import annotations

import json
import os
import argparse
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent_runtime.local_permission_broker import (
    BROKER_VERSION,
    HOST_ACK_KIND,
    HOST_CAPABILITY_KIND,
    HOST_DIAGNOSTICS_FILE,
    HOST_DIAGNOSTICS_KIND,
    HOST_HEALTH_FILE,
    HOST_HEALTH_KIND,
    HOST_IDENTITY_KIND,
    HOST_TOOL_RESOLUTION_KIND,
    HOST_WORKER_CONTROL_KIND,
    atomic_json_write,
    sign_payload,
    verify_payload,
)
from agent_runtime.toolchains.registration import fingerprint, prepare_toolchain
from agent_workbench.host_capabilities import HostCapabilityError, HostCapabilityManager
from agent_workbench.host_identity import HostIdentityError, HostIdentityProcessManager

from .host_tools import resolve_host_tool


HEARTBEAT_INTERVAL_SECONDS = 0.25
MAX_WORKER_EVENTS = 32


class HostWorker:
    """Restartable Desktop Host execution plane.

    The worker owns all potentially blocking host providers. The desktop
    supervisor owns only this process and the signed control/status files.
    """

    def __init__(
        self,
        directory: Path,
        secret: bytes,
        *,
        host_instance_id: str,
        generation: str,
        generation_index: int,
    ) -> None:
        self.directory = directory.resolve()
        self.secret = secret
        self.host_instance_id = host_instance_id
        self.generation = generation
        self.generation_index = generation_index
        self.host_capabilities = HostCapabilityManager(
            self.directory / "host-execution",
            generation=generation,
        )
        self.host_identity = HostIdentityProcessManager(self.directory / "host-identity")
        # Keep independent provider queues so one blocked Browser/CDP request
        # cannot starve host tool discovery, Host Identity, or worker control.
        self._executors = {
            HOST_TOOL_RESOLUTION_KIND: ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="mmx-host-tool",
            ),
            HOST_CAPABILITY_KIND: ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix="mmx-host-capability",
            ),
            HOST_IDENTITY_KIND: ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="mmx-host-identity",
            ),
            HOST_WORKER_CONTROL_KIND: ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="mmx-host-control",
            ),
        }
        self._active: dict[str, dict[str, Any]] = {}
        self._active_lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_WORKER_EVENTS)
        self._submitted: set[str] = set()
        self._desktop_stop_at_ms: dict[str, int] = {}
        self._last_heartbeat = 0.0

    def _signed_write(self, path: Path, payload: dict[str, Any]) -> None:
        payload["signature"] = sign_payload(self.secret, payload)
        atomic_json_write(path, payload)

    def _record_event(self, event: str, **details: Any) -> None:
        self._events.append(
            {
                "at_ms": int(time.time() * 1000),
                "event": event,
                **{
                    key: value
                    for key, value in details.items()
                    if key not in {"secret", "token", "environment", "env"}
                },
            }
        )

    def _write_health(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_heartbeat < HEARTBEAT_INTERVAL_SECONDS:
            return
        with self._active_lock:
            active = tuple(self._active.values())
        active_by_kind: dict[str, int] = {}
        for item in active:
            kind = str(item.get("kind") or "")
            active_by_kind[kind] = active_by_kind.get(kind, 0) + 1
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_HEALTH_KIND,
            "host_instance_id": self.host_instance_id,
            "generation": self.generation,
            "generation_index": self.generation_index,
            "updated_at_ms": int(time.time() * 1000),
            "worker_pid": os.getpid(),
            "active_requests": len(active),
            "active_by_kind": active_by_kind,
        }
        self._signed_write(self.directory / HOST_HEALTH_FILE, payload)
        diagnostics: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_DIAGNOSTICS_KIND,
            "host_instance_id": self.host_instance_id,
            "generation": self.generation,
            "generation_index": self.generation_index,
            "worker_pid": os.getpid(),
            "updated_at_ms": payload["updated_at_ms"],
            "providers": self.host_capabilities.catalog(),
            "active": [dict(item) for item in active[:16]],
            "events": list(self._events),
        }
        self._signed_write(self.directory / HOST_DIAGNOSTICS_FILE, diagnostics)
        self._last_heartbeat = now

    def _load_request(self, path: Path, *, kind: str) -> dict[str, Any] | None:
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
        if int(raw.get("expires_at", 0)) <= int(time.time()):
            return None
        return raw

    def _ack(self, path: Path, raw: dict[str, Any], *, kind: str) -> None:
        request_id = str(raw.get("request_id") or "")
        ack_path = self.directory / path.name.replace(".request.json", ".ack.json")
        self._signed_write(
            ack_path,
            {
                "version": BROKER_VERSION,
                "kind": HOST_ACK_KIND,
                "request_kind": kind,
                "request_id": request_id,
                "server_id": str(raw.get("server_id") or ""),
                "generation": self.generation,
                "acknowledged_at_ms": int(time.time() * 1000),
            },
        )

    def _submit(self, path: Path, *, kind: str, handler: Any) -> None:
        raw = self._load_request(path, kind=kind)
        if raw is None:
            return
        request_id = str(raw.get("request_id") or "")
        if not request_id or request_id in self._submitted:
            return
        self._submitted.add(request_id)
        if str(raw.get("generation") or "") != self.generation:
            self._write_error_response(
                path,
                raw,
                kind=kind,
                error="Host generation 已变化，请重新发起请求。",
                cause_code=(
                    "SESSION_EXPIRED"
                    if kind == HOST_CAPABILITY_KIND
                    and str(raw.get("capability") or "") == "browser"
                    and str(raw.get("session_id") or "")
                    else "HOST_GENERATION_CHANGED"
                ),
                stage="preflight",
            )
            return
        self._ack(path, raw, kind=kind)
        with self._active_lock:
            self._active[request_id] = {
                "request_id": request_id,
                "kind": kind,
                "server_id": str(raw.get("server_id") or ""),
                "capability": str(raw.get("capability") or ""),
                "started_at_ms": int(time.time() * 1000),
            }

        def run() -> None:
            try:
                handler(path, raw)
            except Exception as exc:
                self._write_error_response(
                    path,
                    raw,
                    kind=kind,
                    error=str(exc) or type(exc).__name__,
                    cause_code="HOST_PROVIDER_INTERNAL_ERROR",
                    stage="provider",
                )
            finally:
                with self._active_lock:
                    self._active.pop(request_id, None)
                self._submitted.discard(request_id)

        executor = self._executors.get(kind)
        if executor is None:
            self._write_error_response(
                path,
                raw,
                kind=kind,
                error="Host Worker has no executor for this request kind.",
                cause_code="HOST_PROTOCOL_MISMATCH",
                stage="preflight",
            )
            return
        executor.submit(run)

    def _base_response(self, raw: dict[str, Any], *, kind: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": kind,
            "request_id": str(raw.get("request_id") or ""),
            "server_id": str(raw.get("server_id") or ""),
            "generation": self.generation,
            "runtime_instance_id": str(raw.get("runtime_instance_id") or ""),
            "provider_start_at_ms": int(time.time() * 1000),
        }
        for key in ("program", "workspace", "capability", "action", "session_id", "command_id"):
            if key in raw:
                payload[key] = raw.get(key)
        return payload

    def _write_error_response(
        self,
        path: Path,
        raw: dict[str, Any],
        *,
        kind: str,
        error: str,
        cause_code: str,
        stage: str,
    ) -> None:
        response_path = self.directory / path.name.replace(".request.json", ".response.json")
        payload = {
            **self._base_response(raw, kind=kind),
            "ok": False,
            "error": error[:4000],
            "cause_code": cause_code,
            "stage": stage,
            "responded_at_ms": int(time.time() * 1000),
        }
        self._signed_write(response_path, payload)
        self._record_event("request_failed", cause_code=cause_code, stage=stage, kind=kind)

    def _respond_host_tool(self, path: Path, raw: dict[str, Any]) -> None:
        program = str(raw.get("program") or "")
        workspace = str(raw.get("workspace") or "")
        try:
            resolution = resolve_host_tool(program, workspace=workspace or None)
            proposal = prepare_toolchain(program, str(resolution["executable"]), [])
            resolver = str(resolution.get("resolver") or "")
            proposal["resolution"] = {
                "source": (
                    "workspace_python_environment"
                    if resolver == "workspace_pyvenv"
                    else "host_command"
                ),
                "resolver": resolver,
                "shell": resolution.get("shell"),
                "shell_mode": resolution.get("shell_mode"),
                "shell_startup_files_evaluated": resolution.get("shell_startup_files_evaluated", False),
                "workspace": resolution.get("workspace", workspace),
                "host_environment_exposed_to_ai": False,
            }
            proposal["proposal_fingerprint"] = fingerprint(
                str(proposal["executable"]), list(proposal["read_roots"])
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._write_error_response(
                path,
                raw,
                kind=HOST_TOOL_RESOLUTION_KIND,
                error=str(exc),
                cause_code="APP_RESOLUTION_FAILED",
                stage="provider",
            )
            return
        response_path = self.directory / path.name.replace(".request.json", ".response.json")
        self._signed_write(
            response_path,
            {
                **self._base_response(raw, kind=HOST_TOOL_RESOLUTION_KIND),
                "ok": True,
                "proposal": proposal,
                "error": "",
                "cause_code": "",
                "stage": "completed",
                "responded_at_ms": int(time.time() * 1000),
            },
        )

    def _respond_host_capability(self, path: Path, raw: dict[str, Any]) -> None:
        capability = str(raw.get("capability") or "")
        action = str(raw.get("action") or "")
        session_id = str(raw.get("session_id") or "")
        parameters = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
        server_id = str(raw.get("server_id") or "")
        if (
            capability == "desktop"
            and action in {"click", "type", "keypress", "scroll", "drag"}
            and int(raw.get("queued_at_ms") or 0)
            <= int(self._desktop_stop_at_ms.get(server_id, 0))
        ):
            self._write_error_response(
                path,
                raw,
                kind=HOST_CAPABILITY_KIND,
                error="本地用户已停止该 Profile 在停止指令之前排队的 Desktop 输入。",
                cause_code="DESKTOP_INPUT_STOPPED",
                stage="input",
            )
            return
        try:
            result = self.host_capabilities.invoke(
                capability,
                action,
                server_id=server_id,
                session_id=session_id,
                parameters=parameters,
            )
        except (HostCapabilityError, OSError, RuntimeError, ValueError) as exc:
            cause_code = str(getattr(exc, "code", "") or "HOST_CAPABILITY_FAILED")
            stage = str(getattr(exc, "stage", "") or "provider")
            self._write_error_response(
                path,
                raw,
                kind=HOST_CAPABILITY_KIND,
                error=str(exc),
                cause_code=cause_code,
                stage=stage,
            )
            return
        response_path = self.directory / path.name.replace(".request.json", ".response.json")
        self._signed_write(
            response_path,
            {
                **self._base_response(raw, kind=HOST_CAPABILITY_KIND),
                "ok": True,
                "result": result,
                "error": "",
                "cause_code": "",
                "stage": "completed",
                "responded_at_ms": int(time.time() * 1000),
            },
        )

    def _respond_host_identity(self, path: Path, raw: dict[str, Any]) -> None:
        try:
            result = self.host_identity.invoke(
                str(raw.get("action") or ""),
                server_id=str(raw.get("server_id") or ""),
                command_id=str(raw.get("command_id") or ""),
                parameters=(raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}),
            )
        except (HostIdentityError, OSError, RuntimeError, ValueError) as exc:
            self._write_error_response(
                path,
                raw,
                kind=HOST_IDENTITY_KIND,
                error=str(exc),
                cause_code="HOST_IDENTITY_FAILED",
                stage="provider",
            )
            return
        response_path = self.directory / path.name.replace(".request.json", ".response.json")
        self._signed_write(
            response_path,
            {
                **self._base_response(raw, kind=HOST_IDENTITY_KIND),
                "ok": True,
                "result": result,
                "error": "",
                "cause_code": "",
                "stage": "completed",
                "responded_at_ms": int(time.time() * 1000),
            },
        )

    def _respond_worker_control(self, path: Path, raw: dict[str, Any]) -> None:
        action = str(raw.get("action") or "")
        server_id = str(raw.get("server_id") or "")
        if action not in {"clear_server", "stop_desktop_input"} or not server_id:
            self._write_error_response(
                path,
                raw,
                kind=HOST_WORKER_CONTROL_KIND,
                error="Unsupported worker control action.",
                cause_code="HOST_CONTROL_INVALID",
                stage="preflight",
            )
            return
        if action == "clear_server":
            self._desktop_stop_at_ms[server_id] = int(time.time() * 1000)
            self.host_capabilities.close_server(server_id)
            self.host_identity.close_server(server_id)
            result = {"server_id": server_id, "cleared": True}
        else:
            self._desktop_stop_at_ms[server_id] = int(time.time() * 1000)
            result = self.host_capabilities.stop_desktop_input(server_id)
        response_path = self.directory / path.name.replace(".request.json", ".response.json")
        self._signed_write(
            response_path,
            {
                **self._base_response(raw, kind=HOST_WORKER_CONTROL_KIND),
                "action": action,
                "ok": True,
                "result": result,
                "error": "",
                "cause_code": "",
                "stage": "completed",
                "responded_at_ms": int(time.time() * 1000),
            },
        )

    def run(self, stop_file: Path) -> None:
        self._record_event("worker_started", generation=self.generation)
        self._write_health(force=True)
        try:
            while not stop_file.exists():
                self._write_health()
                for path in tuple(self.directory.glob("*.host-tool.request.json")):
                    self._submit(path, kind=HOST_TOOL_RESOLUTION_KIND, handler=self._respond_host_tool)
                for path in tuple(self.directory.glob("*.host-capability.request.json")):
                    self._submit(path, kind=HOST_CAPABILITY_KIND, handler=self._respond_host_capability)
                for path in tuple(self.directory.glob("*.host-identity.request.json")):
                    self._submit(path, kind=HOST_IDENTITY_KIND, handler=self._respond_host_identity)
                for path in tuple(self.directory.glob("*.worker-control.request.json")):
                    self._submit(path, kind=HOST_WORKER_CONTROL_KIND, handler=self._respond_worker_control)
                time.sleep(0.05)
        finally:
            self._record_event("worker_stopping", generation=self.generation)
            for executor in self._executors.values():
                executor.shutdown(wait=False, cancel_futures=True)
            self.host_capabilities.close()
            self.host_identity.close()


def run_host_worker(
    directory: str,
    secret_hex: str,
    host_instance_id: str,
    generation: str,
    generation_index: int,
    stop_file: str,
) -> None:
    worker = HostWorker(
        Path(directory),
        bytes.fromhex(secret_hex),
        host_instance_id=host_instance_id,
        generation=generation,
        generation_index=generation_index,
    )
    worker.run(Path(stop_file))


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument("--host-instance-id", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--generation-index", required=True, type=int)
    parser.add_argument("--stop-file", required=True)
    args = parser.parse_args(argv)
    run_host_worker(
        args.directory,
        args.secret,
        args.host_instance_id,
        args.generation,
        args.generation_index,
        args.stop_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())


__all__ = ["HostWorker", "cli_main", "run_host_worker"]
