from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ...errors import ToolError
from ...local_permission_broker import (
    LocalPermissionBrokerClient,
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)
from ...permissions.context import ACTIVE_PERMISSIONS
from ...processes import command_payload
from ...route_probe import ROUTE_PROBE_TOKEN_ENV
from .._shared import truncate_text
from .policy import (
    ProcessCommandPolicy,
    SENSITIVE_ENV_RE,
    WINDOWS_BATCH_META_RE,
)


class ProcessHandlers:
    """Command execution, process lifecycle and retained output handlers."""

    def _command_env(self, overrides: dict[str, str]) -> dict[str, str]:
        if self.permission_mode == "dangerous":
            env = os.environ.copy()
        else:
            allowed = {
                "PATH",
                "LANG",
                "LC_ALL",
                "TERM",
                "PATHEXT",
                "COMSPEC",
                "SYSTEMROOT",
                "WINDIR",
                "PROGRAMDATA",
                "PROGRAMFILES",
                "PROGRAMFILES(X86)",
                "PROGRAMW6432",
            }
            env = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in allowed and not SENSITIVE_ENV_RE.search(key)
            }
            env["PATH"] = os.pathsep.join(self.safe_exec_path)
            env.update(
                {
                    "HOME": str(self.commands.home_dir),
                    "TMPDIR": str(self.commands.tmp_dir),
                    "TEMP": str(self.commands.tmp_dir),
                    "TMP": str(self.commands.tmp_dir),
                }
            )
            if os.name == "nt":
                roaming = self.commands.home_dir / "AppData" / "Roaming"
                local = self.commands.home_dir / "AppData" / "Local"
                roaming.mkdir(parents=True, exist_ok=True)
                local.mkdir(parents=True, exist_ok=True)
                home_drive, home_tail = os.path.splitdrive(str(self.commands.home_dir))
                env.update(
                    {
                        "USERPROFILE": str(self.commands.home_dir),
                        "HOMEDRIVE": home_drive,
                        "HOMEPATH": home_tail or "\\",
                        "APPDATA": str(roaming),
                        "LOCALAPPDATA": str(local),
                    }
                )
        env.update(overrides)
        if self.permission_mode == "dangerous" and self.registered_bin_dir:
            env["PATH"] = os.pathsep.join([str(self.registered_bin_dir), env.get("PATH", "")])
        if self.toolchain_registrations and self.permission_mode != "dangerous":
            from ...toolchains.registration import toolchain_environment
            env.update(toolchain_environment(
                self.safe_exec_path, Path.home(), self.commands.cache_dir, self.commands.tmp_dir,
            ))
        for internal_name in (
            "AGENT_RUNTIME_TOOLCHAINS",
            BROKER_DIR_ENV,
            BROKER_SECRET_ENV,
            BROKER_SERVER_ID_ENV,
            ROUTE_PROBE_TOKEN_ENV,
        ):
            env.pop(internal_name, None)
        if (
            self.permission_mode == "safe"
            and not self.allow_network
            and not self._permission_granted("network")
        ):
            env.update(
                {
                    "GOPROXY": "off",
                    "GOTOOLCHAIN": "local",
                    "PIP_NO_INDEX": "1",
                    "npm_config_offline": "true",
                    "YARN_ENABLE_NETWORK": "0",
                    "CARGO_NET_OFFLINE": "true",
                }
            )
        return env

    def _validate_command(
        self,
        cmd: str,
        env: dict[str, str],
        timeout_ms: int,
    ) -> None:
        self._verify_registered_toolchains()
        ProcessCommandPolicy(
            permission_mode=self.permission_mode,
            allow_network=self.allow_network,
            kernel_confined=(self.process_sandbox.state.enabled
                             and self.process_sandbox.state.filesystem_isolation
                             and self.process_sandbox.state.network_isolation),
            permission_granted=self._permission_granted,
            validate_writable_path=self._validate_command_path,
        ).validate(cmd, env, timeout_ms)

    def _validate_command_path(self, raw: str) -> object:
        # Registered entrypoints are outside the workspace but read-only in the kernel.
        if any(raw == item["executable"] for item in self.toolchain_registrations):
            return None
        return self.workspace.writable(raw)

    def _resolve_program(self, program: str) -> str:
        resolved = self.toolchains.resolve_program(program)
        if resolved is not None:
            return resolved
        from ...toolchains.registration import PROGRAMS
        if program in PROGRAMS:
            return self._register_missing_toolchain(program)
        raise ToolError(
            "EXECUTABLE_NOT_FOUND",
            f"已配置的工具路径中未找到 {program}；不会读取登录环境或临时开放 Home。"
            "此程序未接入工具链注册，可使用工作区内程序的明确路径。",
            "process", False, {"program": program, "safe_path": list(self.safe_exec_path)},
        )

    def _register_missing_toolchain(self, program: str) -> str:
        from ...toolchains.discovery import discover_toolchain
        with self._toolchain_registration_lock:
            existing = next((r for r in self.toolchain_registrations if r["program"] == program), None)
            if existing:
                return existing["executable"]
            if program in self._toolchain_consent_denied:
                raise ToolError("TOOLCHAIN_APPROVAL_DENIED", "本次服务会话已拒绝工具链注册；可在桌面手动注册后重启。", "permission", False)
            proposal = discover_toolchain(program, self.workspace.root)
            if proposal is None:
                raise ToolError("EXECUTABLE_NOT_FOUND", f"未能自动定位 {program}，请在服务设置中手动选择路径。未读取登录脚本。", "process", False)
            if not isinstance(self.local_permission_broker, LocalPermissionBrokerClient):
                raise ToolError(
                    "TOOLCHAIN_REGISTRATION_REQUIRED",
                    "已发现工具，但当前连接没有桌面注册确认通道；请在桌面注册并加载配置后重试。",
                    "permission", False, {"proposal": proposal},
                )
            isolation_note = ("当前为危险模式，原命令及子进程没有任务隔离，仅注册验证在沙箱内进行。"
                              if self.permission_mode == "dangerous" else
                              "仅增加所列只读目录，子进程仍受沙箱限制。")
            decision = self.local_permission_broker.request(
                tool_name="register_toolchain", arguments={**proposal, "workspace": str(self.workspace.root)}, permission="toolchain_registration",
                reason=f"AI 首次使用 {program}，已自动找到以下路径。允许后验证并记住当前 Profile 的工具链，继续原命令。{isolation_note}",
                principal="toolchain-registration",
            )
            if not decision.approved or not decision.registration:
                if decision.denied:
                    self._toolchain_consent_denied.add(program)
                raise ToolError("TOOLCHAIN_APPROVAL_REQUIRED", "工具链尚未获得桌面确认，未执行命令。", "permission", False)
            record = decision.registration
            if any(record.get(k) != proposal[k] for k in ("program", "executable", "read_roots")):
                raise ToolError("TOOLCHAIN_APPROVAL_INVALID", "工具链批准范围与请求不一致。", "permission", False)
            self._install_registered_toolchain(record)
            return record["executable"]

    def _validate_process(
        self,
        program: str,
        argv: list[str],
        env: dict[str, str],
        timeout_ms: int,
    ) -> str:
        display = subprocess.list2cmdline([program, *argv])
        self._validate_command(display, env, timeout_ms)
        return self._resolve_program(program)

    def _command_workdir(self, args: dict[str, Any], *, label: str) -> Path:
        cwd = self.workspace.existing(
            str(args.get("cwd") or args.get("workdir", "."))
        ).absolute
        if not cwd.is_dir():
            raise ToolError(
                "NOT_DIRECTORY",
                f"{label} workdir is not a directory",
                "filesystem",
            )
        return cwd

    @staticmethod
    def _process_launch_command(resolved_program: str, argv: list[str]) -> list[str]:
        if os.name != "nt" or Path(resolved_program).suffix.lower() not in {".cmd", ".bat"}:
            return [resolved_program, *argv]
        unsafe = [item for item in argv if WINDOWS_BATCH_META_RE.search(item)]
        if unsafe:
            raise ToolError(
                "PERMISSION_REQUIRED",
                "Windows batch arguments containing cmd.exe metacharacters are blocked",
                "permission",
                False,
                {"permission": "shell_expansion", "arguments": unsafe},
            )
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        quoted_program = f'"{resolved_program}"'
        quoted_args = " ".join(f'"{item}"' for item in argv)
        command_line = f'{quoted_program}{(" " + quoted_args) if quoted_args else ""}'
        return [comspec, "/d", "/v:off", "/s", "/c", command_line]

    def exec_process(self, args: dict[str, Any]) -> dict[str, Any]:
        program = str(args["program"])
        argv = [str(item) for item in list(args.get("args") or [])]
        timeout_ms = int(args.get("timeout_ms", 30_000))
        env_overrides = {
            str(key): str(value) for key, value in dict(args.get("env") or {}).items()
        }
        resolved_program = self._validate_process(
            program, argv, env_overrides, timeout_ms
        )
        cwd = self._command_workdir(args, label="process")
        command = self._process_launch_command(resolved_program, argv)
        command = self.process_sandbox.wrap(
            command,
            cwd=cwd,
            permissions=ACTIVE_PERMISSIONS.get(),
        )
        process_env = self._command_env(env_overrides)
        managed = self.commands.start(
            command,
            cwd=cwd,
            env=process_env,
            stdin_text=str(args.get("stdin", "")),
            timeout_ms=timeout_ms,
            tty=bool(args.get("tty", False)),
            shell=False,
        )
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        payload = command_payload(
            managed, int(args.get("max_output_bytes", 65_536))
        )
        payload["program"] = resolved_program
        payload["argv"] = argv
        payload["shell"] = False
        return self._format_command_payload(payload, args)

    @staticmethod
    def _shell_program_names(cmd: str) -> list[str]:
        builtins = {
            ".", ":", "alias", "bg", "break", "cd", "continue", "echo",
            "eval", "exec", "exit", "export", "false", "fg", "getopts",
            "hash", "jobs", "printf", "pwd", "read", "readonly", "return",
            "set", "shift", "test", "times", "trap", "true", "type",
            "ulimit", "umask", "unalias", "unset", "wait",
        }
        prefixes = {
            "do", "done", "elif", "else", "fi", "if", "then", "while", "until"
        }
        control_heads = {
            "case", "esac", "for", "function", "in", "select", "{", "}"
        }
        wrappers = {"builtin", "command", "env", "time"}
        names: list[str] = []
        for segment in re.split(r"(?:&&|\|\||[;|])", cmd):
            try:
                tokens = shlex.split(segment, posix=os.name != "nt")
            except ValueError:
                continue
            if tokens and tokens[0] in control_heads:
                continue
            while tokens and (
                tokens[0] in prefixes
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])
            ):
                tokens.pop(0)
            while tokens and tokens[0] in wrappers:
                tokens.pop(0)
                while tokens and (
                    tokens[0].startswith("-")
                    or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])
                ):
                    tokens.pop(0)
            if not tokens:
                continue
            name = tokens[0]
            if name in builtins or "/" in name or "\\" in name:
                continue
            if name not in names:
                names.append(name)
        return names

    def _ensure_shell_programs(self, cmd: str) -> None:
        for program in self._shell_program_names(cmd):
            self._resolve_program(program)

    def _shell_launch_command(
        self,
        cmd: str,
        *,
        cwd: Path,
    ) -> tuple[str | list[str], bool]:
        if self.permission_mode == "dangerous":
            return cmd, True
        if os.name == "nt":
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            command: list[str] = [comspec, "/d", "/s", "/c", cmd]
        else:
            command = ["/bin/sh", "-c", cmd]
        return (
            self.process_sandbox.wrap(
                command,
                cwd=cwd,
                permissions=ACTIVE_PERMISSIONS.get(),
            ),
            False,
        )

    def exec_command(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = str(args["cmd"])
        timeout_ms = int(args.get("timeout_ms", 30_000))
        env_overrides = {
            str(key): str(value) for key, value in dict(args.get("env") or {}).items()
        }
        self._validate_command(cmd, env_overrides, timeout_ms)
        cwd = self._command_workdir(args, label="command")
        self._ensure_shell_programs(cmd)
        launch_command, launch_shell = self._shell_launch_command(cmd, cwd=cwd)
        command_env = self._command_env(env_overrides)
        managed = self.commands.start(
            launch_command,
            cwd=cwd,
            env=command_env,
            stdin_text=str(args.get("stdin", "")),
            timeout_ms=timeout_ms,
            tty=bool(args.get("tty", False)),
            shell=launch_shell,
        )
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        return self._format_command_payload(
            command_payload(managed, int(args.get("max_output_bytes", 65_536))),
            args,
        )

    def write_stdin(self, args: dict[str, Any]) -> dict[str, Any]:
        managed = self.commands.write(
            str(args["command_id"]), str(args.get("chars", ""))
        )
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        return self._format_command_payload(
            command_payload(managed, int(args.get("max_output_bytes", 65_536))),
            args,
        )

    def kill_command(self, args: dict[str, Any]) -> dict[str, Any]:
        command_id = str(args["command_id"])
        status = self.commands.terminate(
            command_id,
            str(args.get("signal", "TERM")),
            wait_ms=int(args.get("wait_ms", 5_000)),
            kill_wait_ms=int(args.get("kill_wait_ms", 2_000)),
        )
        managed = self.commands.get(command_id)
        payload = command_payload(
            managed, int(args.get("max_output_bytes", 65_536))
        )
        payload["status"] = status
        return self._format_command_payload(payload, args)

    def _format_command_payload(
        self,
        payload: dict[str, Any],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if payload.get("status") == "running" and payload.get("command_id"):
            payload["next_action"] = {
                "tool": "process_control",
                "arguments": {
                    "action": "write",
                    "command_id": payload["command_id"],
                    "chars": "",
                    "yield_time_ms": 10_000,
                },
            }
        verbosity = str(args.get("verbosity") or "").strip().lower()
        if not verbosity or verbosity == "full":
            return payload
        if verbosity not in {"summary", "preview"}:
            raise ToolError(
                "INVALID_ARGUMENT",
                "verbosity must be one of: summary, preview, full",
                "validation",
            )
        elapsed = float(payload.get("elapsed_ms") or 0) / 1000.0
        exit_code = payload.get("exit_code")
        state = (
            f"exit {exit_code}"
            if exit_code is not None
            else str(payload.get("status", "running"))
        )
        summary = f"{state} | {elapsed:.1f}s"
        compact = {
            key: value
            for key, value in payload.items()
            if key not in {"stdout", "stderr"}
        }
        compact["summary"] = summary
        if verbosity == "preview":
            sections: list[str] = []
            stdout = payload.get("stdout")
            stderr = payload.get("stderr")
            if isinstance(stdout, str) and stdout:
                sections.append(f"--- stdout ---\n{stdout}")
            if isinstance(stderr, str) and stderr:
                sections.append(f"--- stderr ---\n{stderr}")
            preview, preview_truncated = truncate_text(
                "\n".join(sections),
                int(args.get("preview_bytes", 4_096)),
            )
            compact["preview"] = preview
            compact["preview_truncated"] = preview_truncated
            compact["truncated"] = bool(
                compact.get("truncated") or preview_truncated
            )
        return compact

    def read_output(self, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args["output_ref"])
        match = re.fullmatch(r"command:([A-Za-z0-9_-]+):(stdout|stderr)", ref)
        if not match:
            raise ToolError(
                "INVALID_OUTPUT_REF",
                "output_ref must be command:<id>:stdout|stderr",
                "validation",
            )
        command = self.commands.get(match.group(1))
        ref_stream = match.group(2)
        stream = str(args.get("stream") or ref_stream)
        if stream != ref_stream:
            raise ToolError(
                "INVALID_ARGUMENT",
                "stream does not match output_ref",
                "validation",
            )
        return dict(
            self.commands.output(
                command,
                stream,
                int(args.get("offset", 0)),
                int(args.get("limit", 4_096)),
            )
        )

    def process_control(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "").strip()
        if action == "write":
            command_id = str(args.get("command_id") or "").strip()
            if not command_id:
                raise ToolError("INVALID_ARGUMENT", "action=write requires command_id", "validation")
            return self.write_stdin({**args, "command_id": command_id})
        if action == "kill":
            command_id = str(args.get("command_id") or "").strip()
            if not command_id:
                raise ToolError("INVALID_ARGUMENT", "action=kill requires command_id", "validation")
            return self.kill_command({**args, "command_id": command_id})
        if action == "read_output":
            output_ref = str(args.get("output_ref") or "").strip()
            if not output_ref:
                raise ToolError("INVALID_ARGUMENT", "action=read_output requires output_ref", "validation")
            return self.read_output({**args, "output_ref": output_ref})
        raise ToolError("INVALID_ARGUMENT", f"unsupported process_control action: {action}", "validation")
