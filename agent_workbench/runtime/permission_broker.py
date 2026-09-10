from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
    BROKER_VERSION,
    HOST_CAPABILITY_KIND,
    HOST_CONTROL_KIND,
    HOST_HEALTH_FILE,
    HOST_HEALTH_KIND,
    HOST_SUPERVISOR_FILE,
    HOST_SUPERVISOR_KIND,
    HOST_WORKER_CONTROL_KIND,
    HOST_IDENTITY_KIND,
    HOST_TOOL_RESOLUTION_KIND,
    WORKFLOW_APPROVAL_KIND,
    atomic_json_write,
    sign_payload,
    verify_payload,
)
from .process import hidden_process_kwargs


class DesktopPermissionBroker:
    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="micromatrix-workbench-permissions-"))
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        self.secret = secrets.token_bytes(32)
        self.host_instance_id = secrets.token_urlsafe(18)
        self._host_generation = 0
        self._host_generation_id = ""
        self._host_restart_count = 0
        self._host_restart_times: deque[float] = deque(maxlen=16)
        self._host_circuit_open = False
        self._host_worker_process: subprocess.Popen[bytes] | None = None
        self._host_worker_stop_file: Path | None = None
        self._host_worker_started_monotonic = 0.0
        self._host_lock = threading.RLock()
        self._host_supervisor_stop = threading.Event()
        self._supervisor_events: deque[dict[str, Any]] = deque(maxlen=32)
        self._start_host_worker()
        if not self._wait_for_worker_ready(timeout=3.0):
            self._record_supervisor_event("initial_worker_ready_timeout")
            self._stop_host_worker(terminate=True)
            self._host_restart_count += 1
            self._start_host_worker()
            if not self._wait_for_worker_ready(timeout=3.0):
                self._record_supervisor_event("initial_worker_retry_failed")
                self._write_supervisor_status("degraded")
        self._host_supervisor_thread = threading.Thread(
            target=self._host_supervisor_loop,
            name="micromatrix-host-supervisor",
            daemon=True,
        )
        self._host_supervisor_thread.start()

    def _record_supervisor_event(self, event: str, **details: Any) -> None:
        self._supervisor_events.append(
            {
                "at_ms": int(time.time() * 1000),
                "event": event,
                **details,
            }
        )

    def _read_worker_health(self) -> dict[str, Any] | None:
        try:
            raw = json.loads((self.directory / HOST_HEALTH_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(raw, dict)
            or not verify_payload(self.secret, raw)
            or raw.get("version") != BROKER_VERSION
            or raw.get("kind") != HOST_HEALTH_KIND
            or str(raw.get("host_instance_id") or "") != self.host_instance_id
            or str(raw.get("generation") or "") != self._host_generation_id
        ):
            return None
        updated_at_ms = int(raw.get("updated_at_ms") or 0)
        age_ms = int(time.time() * 1000) - updated_at_ms
        if updated_at_ms <= 0 or age_ms < 0 or age_ms > 750:
            return None
        return raw

    def _write_supervisor_status(self, state: str) -> None:
        health = self._read_worker_health()
        process = self._host_worker_process
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_SUPERVISOR_KIND,
            "host_instance_id": self.host_instance_id,
            "state": state,
            "generation": self._host_generation_id,
            "generation_index": self._host_generation,
            "supervisor_pid": os.getpid(),
            "worker_pid": process.pid if process is not None and process.poll() is None else None,
            "worker_alive": bool(process is not None and process.poll() is None),
            "heartbeat_at_ms": int(health.get("updated_at_ms") or 0) if health else None,
            "restart_count": self._host_restart_count,
            "circuit_open": self._host_circuit_open,
            "events": list(self._supervisor_events),
            "updated_at_ms": int(time.time() * 1000),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(self.directory / HOST_SUPERVISOR_FILE, payload)
        except OSError:
            pass

    def _start_host_worker(self) -> None:
        with self._host_lock:
            self._host_generation += 1
            self._host_generation_id = secrets.token_urlsafe(16)
            try:
                (self.directory / HOST_HEALTH_FILE).unlink()
            except FileNotFoundError:
                pass
            stop_file = self.directory / f"host-worker-{self._host_generation}.stop"
            try:
                stop_file.unlink()
            except FileNotFoundError:
                pass
            worker_args = [
                "--directory",
                str(self.directory),
                "--secret",
                self.secret.hex(),
                "--host-instance-id",
                self.host_instance_id,
                "--generation",
                self._host_generation_id,
                "--generation-index",
                str(self._host_generation),
                "--stop-file",
                str(stop_file),
            ]
            command = (
                [sys.executable, "--host-worker", *worker_args]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "agent_workbench.runtime.host_worker", *worker_args]
            )
            stdout_path = self.directory / "host-worker.stdout.log"
            stderr_path = self.directory / "host-worker.stderr.log"
            with stdout_path.open("ab", buffering=0) as stdout_handle, stderr_path.open("ab", buffering=0) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=str(Path(__file__).resolve().parents[2]),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    **hidden_process_kwargs(),
                )
            self._host_worker_stop_file = stop_file
            self._host_worker_process = process
            self._host_worker_started_monotonic = time.monotonic()
            self._record_supervisor_event(
                "worker_started",
                generation=self._host_generation_id,
                generation_index=self._host_generation,
                worker_pid=process.pid,
            )
            self._write_supervisor_status("connecting")

    def _stop_host_worker(self, *, terminate: bool = False) -> None:
        with self._host_lock:
            process = self._host_worker_process
            stop_file = self._host_worker_stop_file
            if process is None:
                return
            if stop_file is not None:
                try:
                    stop_file.touch(mode=0o600, exist_ok=True)
                except OSError:
                    pass
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is None and terminate:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
            self._host_worker_process = None
            self._host_worker_stop_file = None
            if stop_file is not None:
                try:
                    stop_file.unlink()
                except FileNotFoundError:
                    pass

    def _wait_for_worker_ready(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            process = self._host_worker_process
            if process is None or process.poll() is not None:
                return False
            health = self._read_worker_health()
            if health is not None:
                self._write_supervisor_status("ready")
                return True
            time.sleep(0.02)
        return False

    def _restart_host_worker(self, *, automatic: bool) -> bool:
        self._write_supervisor_status("restarting")
        self._stop_host_worker(terminate=True)
        if not automatic:
            self._host_circuit_open = False
            self._host_restart_times.clear()
        self._host_restart_count += 1
        self._start_host_worker()
        ready = self._wait_for_worker_ready(timeout=2.0)
        self._record_supervisor_event(
            "worker_restart_completed" if ready else "worker_restart_failed",
            generation=self._host_generation_id,
            automatic=automatic,
        )
        self._write_supervisor_status("ready" if ready else "degraded")
        return ready

    def _host_supervisor_loop(self) -> None:
        while not self._host_supervisor_stop.wait(0.1):
            for path in tuple(self.directory.glob("*.host-control.request.json")):
                try:
                    self._respond_host_control_request(path)
                except Exception as exc:
                    self._record_supervisor_event("control_request_failed", error=str(exc)[:1000])
            process = self._host_worker_process
            if process is not None and process.poll() is None:
                if self._read_worker_health() is not None:
                    self._write_supervisor_status("ready")
                    continue
                startup_age = time.monotonic() - self._host_worker_started_monotonic
                if startup_age < 3.0:
                    self._write_supervisor_status("connecting")
                    continue
                if not self._prepare_automatic_restart("worker_unresponsive"):
                    continue
                self._restart_host_worker(automatic=True)
                continue
            if self._host_circuit_open:
                self._write_supervisor_status("disconnected")
                continue
            if not self._prepare_automatic_restart("worker_exit_detected"):
                continue
            self._restart_host_worker(automatic=True)

    def _prepare_automatic_restart(self, event: str) -> bool:
        if self._host_circuit_open:
            self._write_supervisor_status("disconnected")
            return False
        now = time.monotonic()
        while self._host_restart_times and now - self._host_restart_times[0] > 30:
            self._host_restart_times.popleft()
        if len(self._host_restart_times) >= 3:
            self._host_circuit_open = True
            self._record_supervisor_event("restart_circuit_open")
            self._write_supervisor_status("disconnected")
            return False
        self._host_restart_times.append(now)
        self._record_supervisor_event(event)
        time.sleep(min(0.4, 0.1 * (2 ** max(0, len(self._host_restart_times) - 1))))
        return True

    def _respond_host_control_request(self, path: Path) -> None:
        request_id = path.name.removesuffix(".host-control.request.json")
        response_path = self.directory / f"{request_id}.host-control.response.json"
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
            or raw.get("kind") != HOST_CONTROL_KIND
            or str(raw.get("request_id") or "") != request_id
            or int(raw.get("expires_at", 0)) <= int(time.time())
        ):
            return
        action = str(raw.get("action") or "")
        if action != "restart":
            ok = False
            error = "Unsupported host control action."
        else:
            ok = self._restart_host_worker(automatic=False)
            error = "" if ok else "Host Worker restart failed."
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_CONTROL_KIND,
            "request_id": request_id,
            "server_id": str(raw.get("server_id") or ""),
            "action": action,
            "ok": ok,
            "error": error,
            "host_instance_id": self.host_instance_id,
            "generation": self._host_generation_id,
            "generation_index": self._host_generation,
            "responded_at_ms": int(time.time() * 1000),
        }
        payload["signature"] = sign_payload(self.secret, payload)
        atomic_json_write(response_path, payload)

    def _send_worker_control(self, action: str, *, server_id: str) -> bool:
        request_id = secrets.token_urlsafe(18)
        request_path = self.directory / f"{request_id}.worker-control.request.json"
        response_path = self.directory / f"{request_id}.worker-control.response.json"
        now = int(time.time())
        payload: dict[str, Any] = {
            "version": BROKER_VERSION,
            "kind": HOST_WORKER_CONTROL_KIND,
            "request_id": request_id,
            "server_id": server_id,
            "action": action,
            "generation": self._host_generation_id,
            "created_at": now,
            "expires_at": now + 2,
        }
        payload["signature"] = sign_payload(self.secret, payload)
        try:
            atomic_json_write(request_path, payload)
        except OSError:
            return False
        deadline = time.monotonic() + 1.0
        try:
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    time.sleep(0.02)
                    continue
                except (OSError, json.JSONDecodeError):
                    return False
                return bool(
                    isinstance(raw, dict)
                    and verify_payload(self.secret, raw)
                    and raw.get("version") == BROKER_VERSION
                    and raw.get("kind") == HOST_WORKER_CONTROL_KIND
                    and raw.get("request_id") == request_id
                    and raw.get("ok") is True
                )
            return False
        finally:
            for target in (request_path, response_path):
                try:
                    target.unlink()
                except FileNotFoundError:
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
                HOST_IDENTITY_KIND,
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
        is_host_identity = raw.get("permission") == "host_identity_use"
        if is_registration:
            if normalized_decision not in {"deny", "remember"}:
                return False
            if normalized_decision == "remember" and not registration:
                return False
        elif is_host_identity and normalized_decision == "session":
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
                HOST_IDENTITY_KIND,
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
        identity_suffix = ".host-identity.request.json"
        for path in self.directory.glob(f"*{identity_suffix}"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not verify_payload(self.secret, raw):
                continue
            if raw.get("kind") != HOST_IDENTITY_KIND:
                continue
            if str(raw.get("server_id") or "") != server_id:
                continue
            request_id = str(raw.get("request_id") or "")
            for target in (
                path,
                self.directory / f"{request_id}.host-identity.response.json",
            ):
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        self._send_worker_control("clear_server", server_id=server_id)

    def cleanup(self) -> None:
        self._host_supervisor_stop.set()
        self._host_supervisor_thread.join(timeout=1.0)
        self._stop_host_worker(terminate=True)
        shutil.rmtree(self.directory, ignore_errors=True)

