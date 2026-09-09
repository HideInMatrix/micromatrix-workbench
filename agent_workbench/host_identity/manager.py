from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)
from agent_runtime.permissions.capabilities import ELICITABLE_PERMISSIONS
from agent_runtime.processes import CommandManager, command_payload
from agent_runtime.sandbox.backend import create_process_sandbox
from agent_runtime.toolchains.paths import system_read_roots
from agent_runtime.toolchains.registration import fingerprint, require_confinement
from agent_runtime.tools.process.policy import WINDOWS_BATCH_META_RE

from .environment import resolve_host_environment


_SECRET_ENV_RE = re.compile(
    r"(token|secret|password|passwd|credential|api[_-]?key|private|access[_-]?key|auth)",
    re.I,
)


class HostIdentityError(RuntimeError):
    """Host identity execution failure safe to surface to Runtime."""


@dataclass(slots=True)
class _HostCommand:
    public_id: str
    internal_id: str
    server_id: str
    workspace: Path
    sandbox_dir: Path
    redactions: tuple[str, ...]


class HostIdentityProcessManager:
    """Execute an exact registered Runtime Tool call with the desktop user's identity.

    This is an execution mode, not a third Tool type. The Runtime still owns
    command validation and user permission. Desktop Host only receives the
    frozen executable/argv/cwd invocation after `host_identity_use` approval.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.commands = CommandManager(self.root)
        self._commands: dict[str, _HostCommand] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _inside(child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _registration(parameters: dict[str, Any], executable: Path) -> tuple[list[str], str]:
        raw = parameters.get("registration")
        if not isinstance(raw, dict):
            raise HostIdentityError("Host identity execution 缺少已确认的 executable registration。")
        if str(raw.get("executable") or "") != str(executable):
            raise HostIdentityError("Host identity executable 与 Runtime registration 不一致。")
        roots = raw.get("read_roots")
        expected = str(raw.get("fingerprint") or "")
        if not isinstance(roots, list) or not roots or not expected:
            raise HostIdentityError("Host identity executable registration 不完整。")
        normalized = [str(item) for item in roots]
        if fingerprint(str(executable), normalized) != expected:
            raise HostIdentityError("Host identity executable 文件身份已变化，请重新注册。")
        return normalized, expected

    @staticmethod
    def _permissions(parameters: dict[str, Any]) -> frozenset[str]:
        raw = parameters.get("permissions")
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(
            str(value)
            for value in raw
            if isinstance(value, str) and value in ELICITABLE_PERMISSIONS
        )

    @staticmethod
    def _redaction_values(env: dict[str, str]) -> tuple[str, ...]:
        values: list[str] = []
        for key, value in env.items():
            if _SECRET_ENV_RE.search(key) and len(value) >= 6 and value not in values:
                values.append(value)
        return tuple(sorted(values, key=len, reverse=True))

    @staticmethod
    def _redact(value: str, secrets: tuple[str, ...]) -> str:
        rendered = value
        for secret in secrets:
            rendered = rendered.replace(secret, "<redacted-host-identity>")
        return rendered

    def _environment(self) -> tuple[dict[str, str], tuple[str, ...]]:
        env = resolve_host_environment(self.root)
        for key in tuple(env):
            if key in {BROKER_DIR_ENV, BROKER_SECRET_ENV, BROKER_SERVER_ID_ENV} or key.startswith(
                "AGENT_RUNTIME_"
            ):
                env.pop(key, None)
        env.update(
            {
                "TMPDIR": str(self.commands.tmp_dir),
                "TEMP": str(self.commands.tmp_dir),
                "TMP": str(self.commands.tmp_dir),
            }
        )
        return env, self._redaction_values(env)

    @staticmethod
    def _home_root(env: dict[str, str]) -> Path:
        raw = str(env.get("HOME") or env.get("USERPROFILE") or "").strip()
        path = Path(raw).expanduser() if raw else Path.home()
        return path.resolve()

    @staticmethod
    def _identity_channel_roots(env: dict[str, str]) -> list[Path]:
        roots: list[Path] = []
        for key, value in env.items():
            if not re.search(r"(?:SOCK|SOCKET)$", key, re.I):
                continue
            path = Path(value).expanduser()
            if path.is_absolute() and path.exists():
                roots.append(path)
        return roots

    @staticmethod
    def _host_path_roots(env: dict[str, str]) -> list[Path]:
        roots: list[Path] = []
        for value in str(env.get("PATH") or "").split(os.pathsep):
            if not value:
                continue
            path = Path(value).expanduser()
            if path.is_absolute() and path.is_dir() and path not in roots:
                roots.append(path)
                if path.name in {"bin", "sbin", "Scripts"} and path.parent.is_dir():
                    roots.append(path.parent)
        return roots

    def _sandboxed_command(
        self,
        *,
        executable: Path,
        argv: list[str],
        workspace: Path,
        cwd: Path,
        registration_roots: list[str],
        protected_paths: list[Path],
        permissions: frozenset[str],
        network_allowed: bool,
        env: dict[str, str],
        sandbox_dir: Path,
    ) -> list[str]:
        readable = [
            self._home_root(env),
            *(Path(item) for item in registration_roots),
            *system_read_roots(),
            *self._host_path_roots(env),
            *self._identity_channel_roots(env),
        ]
        protected = [Path(item) for item in registration_roots]
        protected.extend(protected_paths)
        backend = create_process_sandbox(
            mode="safe",
            workspace=workspace,
            runtime_dir=sandbox_dir,
            readable_roots=readable,
            writable_roots=[workspace, self.commands.runtime_dir],
            protected_paths=protected,
            network=network_allowed,
        )
        require_confinement(backend)
        launch = self._launch_command(executable, argv, env)
        return backend.wrap(
            launch,
            cwd=cwd,
            permissions=permissions,
        )

    @staticmethod
    def _launch_command(executable: Path, argv: list[str], env: dict[str, str]) -> list[str]:
        if os.name != "nt" or executable.suffix.lower() not in {".cmd", ".bat"}:
            return [str(executable), *argv]
        unsafe = [value for value in argv if WINDOWS_BATCH_META_RE.search(value)]
        if unsafe:
            raise HostIdentityError("Windows Host identity batch arguments 包含不安全的 cmd.exe 元字符。")
        comspec = str(env.get("COMSPEC") or os.environ.get("COMSPEC") or "cmd.exe")
        command_line = subprocess.list2cmdline([str(executable), *argv])
        return [comspec, "/d", "/v:off", "/s", "/c", command_line]

    def _public_payload(
        self,
        command: _HostCommand,
        *,
        max_output_bytes: int,
    ) -> dict[str, Any]:
        managed = self.commands.get(command.internal_id)
        payload = command_payload(managed, max_output_bytes)
        payload["command_id"] = command.public_id
        payload["stdout_ref"] = f"command:{command.public_id}:stdout"
        payload["stderr_ref"] = f"command:{command.public_id}:stderr"
        payload["stdout"] = self._redact(str(payload.get("stdout") or ""), command.redactions)
        payload["stderr"] = self._redact(str(payload.get("stderr") or ""), command.redactions)
        payload["host_identity"] = True
        payload["host_environment_exposed_to_ai"] = False
        return payload

    def _command(self, server_id: str, public_id: str) -> _HostCommand:
        with self._lock:
            command = self._commands.get(public_id)
        if command is None:
            raise HostIdentityError(f"unknown or expired host identity command_id: {public_id}")
        if command.server_id != server_id:
            raise HostIdentityError("Host identity command 不属于当前 Server。")
        return command

    def _start(self, server_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        executable = Path(str(parameters.get("executable") or "")).expanduser()
        workspace = Path(str(parameters.get("workspace") or "")).expanduser()
        cwd = Path(str(parameters.get("cwd") or "")).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise HostIdentityError("Host identity executable 必须是存在的绝对可执行文件。")
        if not workspace.is_absolute() or not workspace.is_dir():
            raise HostIdentityError("Host identity workspace 无效。")
        if not cwd.is_absolute() or not cwd.is_dir() or not self._inside(cwd, workspace):
            raise HostIdentityError("Host identity cwd 必须位于当前 Workspace。")
        registration_roots, _ = self._registration(parameters, executable)
        raw_protected = parameters.get("protected_paths")
        if not isinstance(raw_protected, list):
            raise HostIdentityError("Host identity protected_paths 无效。")
        protected_paths: list[Path] = []
        for raw in raw_protected:
            path = Path(str(raw)).expanduser().resolve()
            if path.exists() and self._inside(path, workspace):
                protected_paths.append(path)
        raw_argv = parameters.get("argv")
        if not isinstance(raw_argv, list) or len(raw_argv) > 512:
            raise HostIdentityError("Host identity argv 无效。")
        argv = [str(item) for item in raw_argv]
        raw_env = parameters.get("env")
        if not isinstance(raw_env, dict) or raw_env:
            raise HostIdentityError("Host identity execution 不接受调用方 env override；使用真实宿主用户环境。")
        timeout_ms = max(1, min(int(parameters.get("timeout_ms") or 30_000), 600_000))
        yield_ms = max(0, min(int(parameters.get("yield_time_ms") or 10_000), 30_000))
        max_output = max(1, min(int(parameters.get("max_output_bytes") or 65_536), 1_048_576))
        permissions = self._permissions(parameters)
        if "host_identity_use" not in permissions:
            raise HostIdentityError("Host identity execution 缺少 host_identity_use 授权。")
        env, redactions = self._environment()
        sandbox_dir = Path(tempfile.mkdtemp(prefix="identity-sandbox-", dir=self.root))
        command = self._sandboxed_command(
            executable=executable,
            argv=argv,
            workspace=workspace.resolve(),
            cwd=cwd.resolve(),
            registration_roots=registration_roots,
            protected_paths=protected_paths,
            permissions=permissions,
            network_allowed=bool(parameters.get("network_allowed", False)),
            env=env,
            sandbox_dir=sandbox_dir,
        )
        managed = self.commands.start(
            command,
            cwd=cwd.resolve(),
            env=env,
            stdin_text=str(parameters.get("stdin") or ""),
            timeout_ms=timeout_ms,
            tty=bool(parameters.get("tty", False)),
            shell=False,
        )
        public_id = f"host_{managed.command_id}"
        record = _HostCommand(
            public_id=public_id,
            internal_id=managed.command_id,
            server_id=server_id,
            workspace=workspace.resolve(),
            sandbox_dir=sandbox_dir,
            redactions=redactions,
        )
        with self._lock:
            self._commands[public_id] = record
        self.commands.wait(managed, yield_ms)
        return self._public_payload(record, max_output_bytes=max_output)

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        command_id: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(parameters or {})
        if action == "start":
            return self._start(server_id, params)
        command = self._command(server_id, command_id)
        managed = self.commands.get(command.internal_id)
        if action == "poll":
            self.commands.wait(managed, max(0, min(int(params.get("yield_time_ms") or 0), 30_000)))
            return self._public_payload(
                command,
                max_output_bytes=max(1, min(int(params.get("max_output_bytes") or 65_536), 1_048_576)),
            )
        if action == "write":
            self.commands.write(command.internal_id, str(params.get("chars") or ""))
            self.commands.wait(managed, max(0, min(int(params.get("yield_time_ms") or 0), 30_000)))
            return self._public_payload(
                command,
                max_output_bytes=max(1, min(int(params.get("max_output_bytes") or 65_536), 1_048_576)),
            )
        if action == "kill":
            status = self.commands.terminate(
                command.internal_id,
                str(params.get("signal") or "TERM"),
                wait_ms=max(0, min(int(params.get("wait_ms") or 5_000), 30_000)),
                kill_wait_ms=max(0, min(int(params.get("kill_wait_ms") or 2_000), 30_000)),
            )
            payload = self._public_payload(
                command,
                max_output_bytes=max(1, min(int(params.get("max_output_bytes") or 65_536), 1_048_576)),
            )
            payload["status"] = status
            return payload
        if action == "read_output":
            stream = str(params.get("stream") or "stdout")
            if stream not in {"stdout", "stderr"}:
                raise HostIdentityError("Host identity read_output stream 无效。")
            payload = dict(
                self.commands.output(
                    managed,
                    stream,
                    max(0, int(params.get("offset") or 0)),
                    max(1, min(int(params.get("limit") or 4_096), 1_048_576)),
                )
            )
            payload["output_ref"] = f"command:{command.public_id}:{stream}"
            payload["content"] = self._redact(str(payload.get("content") or ""), command.redactions)
            payload["data"] = payload["content"]
            payload["host_identity"] = True
            return payload
        raise HostIdentityError(f"unsupported Host identity action: {action}")

    def close_server(self, server_id: str) -> None:
        with self._lock:
            commands = tuple(self._commands.items())
        for public_id, command in commands:
            if command.server_id != server_id:
                continue
            try:
                managed = self.commands.get(command.internal_id)
                if managed.process.poll() is None:
                    self.commands.terminate(command.internal_id, "TERM", wait_ms=300, kill_wait_ms=300)
            except Exception:
                pass
            with self._lock:
                self._commands.pop(public_id, None)
            shutil.rmtree(command.sandbox_dir, ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            server_ids = {command.server_id for command in self._commands.values()}
        for server_id in server_ids:
            self.close_server(server_id)
        self.commands.close()
        shutil.rmtree(self.commands.runtime_dir, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)
