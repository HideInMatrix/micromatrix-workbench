from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ...errors import ToolError
from ...host_identity import HostIdentityRuntimeClient
from ...local_permission_broker import (
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

    def _host_tool_broker(self) -> Any | None:
        broker = self.local_permission_broker
        if not callable(getattr(broker, "resolve_host_tool", None)):
            return None
        if not callable(getattr(broker, "request", None)):
            return None
        return broker

    def _host_identity(self) -> HostIdentityRuntimeClient:
        client = getattr(self, "_host_identity_runtime_client", None)
        if not isinstance(client, HostIdentityRuntimeClient):
            client = HostIdentityRuntimeClient(self)
            setattr(self, "_host_identity_runtime_client", client)
        return client

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
                    "XDG_CONFIG_HOME": str(self.commands.config_dir),
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
                self.safe_exec_path,
                Path.home(),
                self.commands.config_dir,
                self.commands.cache_dir,
                self.commands.tmp_dir,
            ))
        for internal_name in (
            "AGENT_RUNTIME_TOOLCHAINS",
            BROKER_DIR_ENV,
            BROKER_SECRET_ENV,
            BROKER_SERVER_ID_ENV,
            ROUTE_PROBE_TOKEN_ENV,
        ):
            env.pop(internal_name, None)
        if self.permission_mode != "dangerous":
            env["GIT_CONFIG_GLOBAL"] = os.devnull
            env["GIT_TERMINAL_PROMPT"] = "0"
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

    @staticmethod
    def _registered_python_alias_matches(
        registration: dict[str, Any],
        candidate: str,
        requirements: list[Any],
    ) -> bool:
        if registration.get("program") not in {"python", "python3"}:
            return False
        context = registration.get("project_context")
        registered_requirements = (
            context.get("requirements") if isinstance(context, dict) else None
        )
        if registered_requirements != requirements:
            return False
        try:
            registered_target = Path(str(registration["executable"])).resolve(strict=True)
            candidate_target = Path(candidate).resolve(strict=True)
        except (KeyError, OSError):
            return False
        return registered_target == candidate_target

    @staticmethod
    def _registered_node_alias_matches(
        registration: dict[str, Any],
        candidate: str,
        requirements: list[Any],
    ) -> bool:
        if registration.get("program") not in {
            "node", "npm", "npx", "corepack", "pnpm", "yarn"
        }:
            return False
        context = registration.get("project_context")
        registered_requirements = (
            context.get("requirements") if isinstance(context, dict) else None
        )
        if registered_requirements != requirements:
            return False
        try:
            candidate_target = Path(candidate).resolve(strict=True)
            roots = [Path(str(value)).resolve(strict=True) for value in registration["read_roots"]]
        except (KeyError, OSError, TypeError):
            return False
        return any(
            candidate_target == root or candidate_target.is_relative_to(root)
            for root in roots
        )

    def _resolve_program(self, program: str, cwd: Path | None = None) -> str:
        from ...toolchains.registration import normalize_program_name
        path = Path(program).expanduser()
        if path.is_absolute() or self.permission_mode == "dangerous":
            resolved = self.toolchains.resolve_program(program)
            if resolved is not None:
                return resolved
            raise ToolError(
                "EXECUTABLE_NOT_FOUND",
                f"已配置的工具路径中未找到 {program}。",
                "process", False, {"program": program, "safe_path": list(self.safe_exec_path)},
            )
        try:
            normalized = normalize_program_name(program)
        except ValueError:
            normalized = ""
        if not normalized:
            raise ToolError(
                "EXECUTABLE_NOT_FOUND",
                f"已配置的工具路径中未找到 {program}，且该名称不能作为主机工具解析。",
                "process", False, {"program": program, "safe_path": list(self.safe_exec_path)},
            )
        current_context = self.toolchains.project_context(
            normalized,
            (cwd or self.workspace.root).resolve(),
        )
        current_requirements = current_context.get("requirements")
        if not isinstance(current_requirements, list):
            current_requirements = []
        project_python_environment = (
            normalized in {"python", "python3"}
            and any(
                isinstance(item, dict)
                and item.get("type") == "python_virtual_environment"
                for item in current_requirements
            )
        )
        project_node_context = (
            normalized in {"node", "npm", "npx", "corepack", "pnpm", "yarn"}
            and any(
                isinstance(item, dict)
                and item.get("type") in {
                    "runtime_version",
                    "node_engine",
                    "package_manager",
                }
                for item in current_requirements
            )
        )
        existing = next(
            (item for item in self.toolchain_registrations if item["program"] == normalized),
            None,
        )
        if existing is not None:
            registered_context = existing.get("project_context")
            registered_requirements = (
                registered_context.get("requirements")
                if isinstance(registered_context, dict)
                else []
            )
            if not isinstance(registered_requirements, list):
                registered_requirements = []
            if current_requirements and not registered_context:
                raise ToolError(
                    "TOOLCHAIN_REGISTRATION_STALE",
                    f"已注册工具 {normalized} 缺少当前项目版本约束绑定，请重新发现并确认注册。",
                    "process",
                    False,
                    {
                        "program": normalized,
                        "reason": "missing_project_context",
                        "current_requirements": current_requirements,
                    },
                )
            if registered_context and registered_requirements != current_requirements:
                raise ToolError(
                    "PROJECT_TOOLCHAIN_MISMATCH",
                    f"项目对 {normalized} 的版本约束已变化，现有工具注册不再适用于当前项目。",
                    "process",
                    False,
                    {
                        "program": normalized,
                        "registered_requirements": registered_requirements,
                        "current_requirements": current_requirements,
                    },
                )
            resolved = self.toolchains.resolve_program(normalized)
            if resolved is None:
                raise ToolError(
                    "TOOLCHAIN_REGISTRATION_STALE",
                    f"已注册工具 {normalized} 当前不可执行，请重新确认注册。",
                    "process", False,
                )
            return resolved
        local = self.toolchains.resolve_program(normalized)
        if project_python_environment and local is not None:
            alias_registration = next(
                (
                    item
                    for item in self.toolchain_registrations
                    if self._registered_python_alias_matches(
                        item,
                        local,
                        current_requirements,
                    )
                ),
                None,
            )
            if alias_registration is not None:
                return local
        if project_node_context and local is not None:
            alias_registration = next(
                (
                    item
                    for item in self.toolchain_registrations
                    if self._registered_node_alias_matches(
                        item,
                        local,
                        current_requirements,
                    )
                ),
                None,
            )
            if alias_registration is not None:
                return local
        if local is not None and not (project_python_environment or project_node_context):
            return local
        if self._host_tool_broker() is None:
            raise ToolError(
                "HOST_TOOL_RESOLUTION_REQUIRED",
                "当前 Runtime 允许的 PATH 中未找到该工具，且没有 Workbench Host 工具发现通道。",
                "permission", False, {"program": normalized},
            )
        proposal = self._resolve_host_tool_proposal(normalized, cwd=cwd)
        return self._register_missing_toolchain(normalized, proposal=proposal)

    def _resolve_host_tool_proposal(
        self,
        program: str,
        *,
        cwd: Path | None = None,
    ) -> dict[str, Any]:
        working_directory = (cwd or self.workspace.root).resolve()
        project_context = self.toolchains.project_context(program, working_directory)
        cache = getattr(self, "_host_tool_resolution_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_host_tool_resolution_cache", cache)
        cache_key = (
            program,
            str(working_directory),
            str(project_context.get("fingerprint") or ""),
        )
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return cached
        broker = self._host_tool_broker()
        if broker is None:
            raise ToolError(
                "HOST_TOOL_RESOLUTION_REQUIRED",
                "当前连接没有 Workbench Host 工具解析通道。",
                "permission", False, {"program": program},
            )
        resolution = broker.resolve_host_tool(program, workspace=working_directory)
        if resolution.status != "resolved" or not isinstance(resolution.proposal, dict):
            code = (
                "EXECUTABLE_NOT_FOUND"
                if resolution.status == "not_found"
                else "HOST_TOOL_RESOLUTION_UNAVAILABLE"
            )
            raise ToolError(
                code,
                resolution.error or f"Workbench Host 未能解析工具 {program}。",
                "process",
                resolution.status in {"timeout", "unavailable"},
                {"program": program, "host_resolution_status": resolution.status},
            )
        proposal = dict(resolution.proposal)
        if proposal.get("program") != program or not proposal.get("executable"):
            raise ToolError(
                "HOST_TOOL_RESOLUTION_INVALID",
                "Workbench Host 返回的工具解析结果无效。",
                "process", False, {"program": program},
            )
        proposal["project_context"] = project_context
        cache[cache_key] = proposal
        return proposal

    def _register_missing_toolchain(
        self,
        program: str,
        *,
        proposal: dict[str, Any] | None = None,
        replace_existing: bool = False,
    ) -> str:
        with self._toolchain_registration_lock:
            existing = next((r for r in self.toolchain_registrations if r["program"] == program), None)
            if existing and not replace_existing:
                return existing["executable"]
            broker = self._host_tool_broker()
            if broker is None:
                raise ToolError(
                    "HOST_TOOL_RESOLUTION_REQUIRED",
                    "当前连接没有 Workbench Host 工具解析与注册确认通道；无法安全查询真实用户环境。",
                    "permission", False, {"program": program},
                )
            proposal = dict(proposal or self._resolve_host_tool_proposal(program))
            if existing and (
                os.path.normcase(os.path.abspath(str(existing["executable"])))
                == os.path.normcase(os.path.abspath(str(proposal["executable"])))
                and set(existing["read_roots"]) == set(proposal.get("read_roots") or [])
            ):
                return existing["executable"]
            consent_key = f"{program}:{proposal.get('proposal_fingerprint') or proposal.get('executable')}"
            if consent_key in self._toolchain_consent_denied:
                raise ToolError("TOOLCHAIN_APPROVAL_DENIED", "本次服务会话已拒绝这个工具解析结果的注册；可在桌面重新确认。", "permission", False)
            context = proposal.get("project_context")
            requirements = context.get("requirements") if isinstance(context, dict) else []
            project_note = (
                f"当前 Workspace 检测到 {len(requirements)} 条项目工具版本约束，并已用于本次 Host 解析上下文。"
                if isinstance(requirements, list) and requirements
                else "当前 Workspace 未检测到该工具的项目版本约束。"
            )
            isolation_note = ("当前为危险模式，原命令及子进程没有任务隔离，仅注册验证在沙箱内进行。"
                              if self.permission_mode == "dangerous" else
                              "仅增加所列只读目录，子进程仍受沙箱限制。")
            decision = broker.request(
                tool_name="register_toolchain",
                arguments={**proposal, "workspace": str(self.workspace.root)},
                permission="toolchain_registration",
                reason=(f"AI 准备在当前 Workspace 使用 {program}。Workbench Host 已通过项目上下文或真实用户环境解析出工具路径；"
                        f"仅把绝对路径与必要只读范围展示给你确认，主机环境变量不会交给 AI。"
                        f"{project_note}{isolation_note}"),
                principal="toolchain-registration",
            )
            if not decision.approved or not decision.registration:
                if decision.denied:
                    self._toolchain_consent_denied.add(consent_key)
                raise ToolError("TOOLCHAIN_APPROVAL_REQUIRED", "工具链尚未获得桌面确认，未执行命令。", "permission", False)
            record = decision.registration
            if any(
                record.get(key) != proposal.get(key)
                for key in ("program", "executable", "read_roots")
            ):
                raise ToolError("TOOLCHAIN_APPROVAL_INVALID", "工具链批准范围与请求不一致。", "permission", False)
            self._install_registered_toolchain(record)
            cache = getattr(self, "_host_tool_resolution_cache", None)
            if isinstance(cache, dict):
                for key in tuple(cache):
                    if isinstance(key, tuple) and key and key[0] == program:
                        cache.pop(key, None)
            return record["executable"]

    def _validate_process(
        self,
        program: str,
        argv: list[str],
        env: dict[str, str],
        timeout_ms: int,
        cwd: Path,
    ) -> str:
        display = subprocess.list2cmdline([program, *argv])
        self._validate_command(display, env, timeout_ms)
        return self._resolve_program(program, cwd=cwd)

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
        cwd = self._command_workdir(args, label="process")
        resolved_program = self._validate_process(
            program, argv, env_overrides, timeout_ms, cwd
        )
        if bool(args.get("use_host_identity", False)):
            return self._format_command_payload(
                self._host_identity().start(
                    executable=resolved_program,
                    argv=argv,
                    cwd=cwd,
                    env_overrides=env_overrides,
                    args=args,
                ),
                args,
            )
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

    def _ensure_shell_programs(self, cmd: str, *, cwd: Path) -> None:
        for program in self._shell_program_names(cmd):
            self._resolve_program(program, cwd=cwd)

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
        self._ensure_shell_programs(cmd, cwd=cwd)
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
        command_id = str(args["command_id"])
        if self._host_identity().is_command_id(command_id):
            payload = self._host_identity().invoke(
                "write",
                command_id=command_id,
                parameters={
                    "chars": str(args.get("chars", "")),
                    "yield_time_ms": int(args.get("yield_time_ms", 10_000)),
                    "max_output_bytes": int(args.get("max_output_bytes", 65_536)),
                },
            )
            return self._format_command_payload(payload, args)
        managed = self.commands.write(
            command_id, str(args.get("chars", ""))
        )
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        return self._format_command_payload(
            command_payload(managed, int(args.get("max_output_bytes", 65_536))),
            args,
        )

    def kill_command(self, args: dict[str, Any]) -> dict[str, Any]:
        command_id = str(args["command_id"])
        if self._host_identity().is_command_id(command_id):
            payload = self._host_identity().invoke(
                "kill",
                command_id=command_id,
                parameters={
                    "signal": str(args.get("signal", "TERM")),
                    "wait_ms": int(args.get("wait_ms", 5_000)),
                    "kill_wait_ms": int(args.get("kill_wait_ms", 2_000)),
                    "max_output_bytes": int(args.get("max_output_bytes", 65_536)),
                },
            )
            return self._format_command_payload(payload, args)
        self.commands.terminate(
            command_id,
            str(args.get("signal", "TERM")),
            wait_ms=int(args.get("wait_ms", 5_000)),
            kill_wait_ms=int(args.get("kill_wait_ms", 2_000)),
        )
        managed = self.commands.get(command_id)
        payload = command_payload(
            managed, int(args.get("max_output_bytes", 65_536))
        )
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
        state = str(payload.get("status", "running"))
        if exit_code is not None:
            state += f" (exit {exit_code})"
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
        command_id = match.group(1)
        ref_stream = match.group(2)
        stream = str(args.get("stream") or ref_stream)
        if stream != ref_stream:
            raise ToolError(
                "INVALID_ARGUMENT",
                "stream does not match output_ref",
                "validation",
            )
        if self._host_identity().is_command_id(command_id):
            return self._host_identity().invoke(
                "read_output",
                command_id=command_id,
                parameters={
                    "stream": stream,
                    "offset": int(args.get("offset", 0)),
                    "limit": int(args.get("limit", 4_096)),
                },
            )
        command = self.commands.get(command_id)
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
            return {"action": action, **self.write_stdin({**args, "command_id": command_id})}
        if action == "kill":
            command_id = str(args.get("command_id") or "").strip()
            if not command_id:
                raise ToolError("INVALID_ARGUMENT", "action=kill requires command_id", "validation")
            return {"action": action, **self.kill_command({**args, "command_id": command_id})}
        if action == "read_output":
            output_ref = str(args.get("output_ref") or "").strip()
            if not output_ref:
                raise ToolError("INVALID_ARGUMENT", "action=read_output requires output_ref", "validation")
            return {"action": action, **self.read_output({**args, "output_ref": output_ref})}
        raise ToolError("INVALID_ARGUMENT", f"unsupported process_control action: {action}", "validation")
