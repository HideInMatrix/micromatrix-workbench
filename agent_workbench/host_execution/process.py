from __future__ import annotations

import os
import json
import hashlib
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

    def __init__(self, root: Path, *, generation: str = "standalone") -> None:
        self.base_root = root.expanduser().resolve()
        self.base_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.generation = generation or "standalone"
        generation_key = hashlib.sha256(self.generation.encode("utf-8")).hexdigest()[:16]
        self.root = self.base_root / f"generation-{generation_key}"
        self._gc_stale_generations()
        self.root.mkdir(mode=0o700, parents=False, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._handles: dict[str, HostProcessHandle] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _owner_manifest(root: Path) -> Path:
        return root / "owner.json"

    @staticmethod
    def _process_command(pid: int) -> str:
        if os.name == "nt":
            return ""
        try:
            completed = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def _owned_stale_process(self, workspace: Path, manifest: dict[str, object]) -> int | None:
        try:
            pid = int(manifest.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        if pid <= 1 or os.name == "nt":
            return None
        if str(manifest.get("workspace") or "") != str(workspace):
            return None
        command = self._process_command(pid)
        executable = Path(str(manifest.get("executable") or "")).expanduser()
        executable_is_owned = False
        try:
            executable.resolve().relative_to(workspace)
            executable_is_owned = executable.is_file()
        except (OSError, ValueError):
            executable_is_owned = False
        if not executable_is_owned and (not command or str(workspace) not in command):
            return None
        try:
            if os.getpgid(pid) != pid:
                return None
        except (ProcessLookupError, OSError):
            return 0
        return pid

    def _gc_stale_generations(self) -> None:
        """Recover only resources whose Workbench ownership can be proven.

        Unknown directories/processes are deliberately preserved. This avoids
        turning startup GC into a generic PID/process cleanup facility.
        """
        candidates = sorted(self.base_root.glob("generation-*"))[:16]
        for generation_root in candidates:
            if generation_root == self.root or not generation_root.is_dir():
                continue
            preserve = False
            for workspace in tuple(generation_root.iterdir()):
                if not workspace.is_dir():
                    preserve = True
                    continue
                manifest_path = self._owner_manifest(workspace)
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    preserve = True
                    continue
                if not isinstance(manifest, dict):
                    preserve = True
                    continue
                owned_pid = self._owned_stale_process(workspace.resolve(), manifest)
                if owned_pid is None:
                    # A live process that cannot be proven to be ours is never killed
                    # and its directory is never deleted.
                    try:
                        pid = int(manifest.get("pid") or 0)
                        os.kill(pid, 0)
                    except (ProcessLookupError, OSError, TypeError, ValueError):
                        shutil.rmtree(workspace, ignore_errors=True)
                    else:
                        preserve = True
                    continue
                if owned_pid > 0:
                    try:
                        os.killpg(owned_pid, signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        pass
                    deadline = time.monotonic() + 1.0
                    while time.monotonic() < deadline:
                        try:
                            os.kill(owned_pid, 0)
                        except (ProcessLookupError, OSError):
                            break
                        time.sleep(0.05)
                    else:
                        try:
                            os.killpg(owned_pid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            preserve = True
                shutil.rmtree(workspace, ignore_errors=True)
            if not preserve:
                try:
                    generation_root.rmdir()
                except OSError:
                    pass

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
        try:
            self._owner_manifest(workspace.root).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "generation": self.generation,
                        "server_id": workspace.server_id,
                        "workspace": str(workspace.root.resolve()),
                        "pid": process.pid,
                        "executable": str(executable),
                        "started_at_ms": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except OSError:
            self.release(handle)
            raise HostExecutionError("无法记录 Workbench Host 进程所有权，已取消启动。")
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
