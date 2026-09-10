from __future__ import annotations

import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from agent_workbench.runtime.process import hidden_process_kwargs

from .environment import host_user_session_environment


class HostExecutionError(RuntimeError):
    """Host process lifecycle failure safe to surface to a capability."""


@dataclass(frozen=True, slots=True)
class HostExecutionWorkspace:
    workspace_id: str
    server_id: str
    root: Path


@dataclass(frozen=True, slots=True)
class HostExecutionRequest:
    executable: Path
    argv: tuple[str, ...] = ()
    cwd: Path | None = None


@dataclass(slots=True)
class HostProcessHandle:
    process_id: str
    server_id: str
    root: Path
    process: subprocess.Popen[bytes]
    stdout_path: Path
    stderr_path: Path
    started_at: float
    redactions: tuple[str, ...]

    def poll(self) -> int | None:
        return self.process.poll()


class HostProcessSupervisor:
    """Desktop-host process/session execution shared by Host Capabilities.

    This layer deliberately does not know any product/tool identity. It owns
    only host process lifecycle, environment boundaries, diagnostics, and
    cleanup.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._handles: dict[str, HostProcessHandle] = {}
        self._lock = threading.RLock()

    def prepare(self, server_id: str) -> HostExecutionWorkspace:
        workspace_id = secrets.token_urlsafe(18)
        root = self.root / workspace_id
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        return HostExecutionWorkspace(workspace_id, server_id, root)

    def launch(
        self,
        workspace: HostExecutionWorkspace,
        request: HostExecutionRequest,
    ) -> HostProcessHandle:
        executable = request.executable.expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            self.discard(workspace)
            raise HostExecutionError("Host executable 不存在或不可执行。")
        workdir = (request.cwd or workspace.root).expanduser().resolve()
        if not workdir.is_dir():
            self.discard(workspace)
            raise HostExecutionError("Host process cwd 不存在。")
        env, redactions = host_user_session_environment()
        stdout_path = workspace.root / "stdout.log"
        stderr_path = workspace.root / "stderr.log"
        try:
            with (
                stdout_path.open("ab", buffering=0) as stdout_handle,
                stderr_path.open("ab", buffering=0) as stderr_handle,
            ):
                process = subprocess.Popen(
                    [str(executable), *request.argv],
                    cwd=str(workdir),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env=env,
                    start_new_session=True,
                    **hidden_process_kwargs(),
                )
        except OSError as exc:
            self.discard(workspace)
            raise HostExecutionError("Desktop Host 无法启动目标进程。") from exc
        process_id = secrets.token_urlsafe(18)
        handle = HostProcessHandle(
            process_id=process_id,
            server_id=workspace.server_id,
            root=workspace.root,
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=time.monotonic(),
            redactions=redactions,
        )
        with self._lock:
            self._handles[process_id] = handle
        return handle

    @staticmethod
    def _redact(value: str, secrets: tuple[str, ...]) -> str:
        rendered = value
        for secret in secrets:
            rendered = rendered.replace(secret, "<redacted-host-value>")
        return rendered

    @staticmethod
    def _tail(path: Path, limit: int) -> str:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit), os.SEEK_SET)
                return handle.read(limit).decode("utf-8", errors="replace")
        except OSError:
            return ""

    def diagnostics(self, handle: HostProcessHandle, *, limit: int = 16_384) -> dict[str, object]:
        returncode = handle.poll()
        signal_name = ""
        if isinstance(returncode, int) and returncode < 0:
            try:
                signal_name = signal.Signals(-returncode).name
            except ValueError:
                signal_name = ""
        return {
            "process_id": handle.process_id,
            "exit_code": returncode,
            "signal": signal_name,
            "elapsed_ms": int((time.monotonic() - handle.started_at) * 1000),
            "stdout_tail": self._redact(self._tail(handle.stdout_path, limit), handle.redactions),
            "stderr_tail": self._redact(self._tail(handle.stderr_path, limit), handle.redactions),
        }

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass

    def release(self, handle: HostProcessHandle) -> None:
        with self._lock:
            self._handles.pop(handle.process_id, None)
        self._terminate_process(handle.process)
        shutil.rmtree(handle.root, ignore_errors=True)

    @staticmethod
    def discard(workspace: HostExecutionWorkspace) -> None:
        shutil.rmtree(workspace.root, ignore_errors=True)

    def close_server(self, server_id: str) -> None:
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            if handle.server_id == server_id:
                self.release(handle)

    def close(self) -> None:
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            self.release(handle)
        shutil.rmtree(self.root, ignore_errors=True)


__all__ = [
    "HostExecutionError",
    "HostExecutionRequest",
    "HostExecutionWorkspace",
    "HostProcessHandle",
    "HostProcessSupervisor",
]
