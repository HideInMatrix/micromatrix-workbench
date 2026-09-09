from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...errors import ToolError
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


@dataclass(frozen=True, slots=True)
class _HostCredentialLaunch:
    session_id: str
    read_root: Path
    askpass_path: Path
    target_host: str


class ProcessHandlers:
    """Command execution, process lifecycle and retained output handlers."""

    def _host_tool_broker(self) -> Any | None:
        broker = self.local_permission_broker
        if not callable(getattr(broker, "resolve_host_tool", None)):
            return None
        if not callable(getattr(broker, "request", None)):
            return None
        return broker

    def _host_credential_broker(self) -> Any | None:
        broker = self.local_permission_broker
        if not callable(getattr(broker, "prepare_host_credential", None)):
            return None
        if not callable(getattr(broker, "release_host_credential", None)):
            return None
        return broker

    @staticmethod
    def _git_subcommand(argv: list[str]) -> tuple[int, str] | None:
        options_with_value = {
            "-C", "-c", "--git-dir", "--work-tree", "--namespace",
            "--super-prefix", "--config-env", "--exec-path",
        }
        index = 0
        while index < len(argv):
            token = argv[index]
            if token == "--":
                index += 1
                return (index, argv[index]) if index < len(argv) else None
            if token in options_with_value:
                index += 2
                continue
            if token.startswith((
                "--git-dir=", "--work-tree=", "--namespace=", "--super-prefix=",
                "--config-env=", "--exec-path=",
            )):
                index += 1
                continue
            if token.startswith("-"):
                index += 1
                continue
            return index, token
        return None

    def _git_read_value(
        self,
        git: str,
        argv: list[str],
        cwd: Path,
    ) -> str:
        try:
            completed = subprocess.run(
                [git, *argv],
                cwd=str(cwd),
                env=self._command_env({}),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def _git_default_push_remote(self, git: str, cwd: Path) -> str:
        branch = self._git_read_value(
            git, ["symbolic-ref", "--quiet", "--short", "HEAD"], cwd
        )
        keys = []
        if branch:
            keys.extend((f"branch.{branch}.pushRemote", f"branch.{branch}.remote"))
        keys.insert(1 if keys else 0, "remote.pushDefault")
        for key in keys:
            value = self._git_read_value(git, ["config", "--get", key], cwd)
            if value and value != ".":
                return value
        return "origin"

    def _git_push_repository(
        self,
        git: str,
        argv: list[str],
        command_index: int,
        cwd: Path,
    ) -> str:
        options_with_value = {"--receive-pack", "--exec", "--repo", "--push-option", "-o"}
        repository = ""
        index = command_index + 1
        while index < len(argv):
            token = argv[index]
            if token in options_with_value:
                if index + 1 < len(argv):
                    if token == "--repo":
                        repository = argv[index + 1]
                    index += 2
                    continue
                break
            if token.startswith("--repo="):
                repository = token.split("=", 1)[1]
                index += 1
                continue
            if token.startswith("-"):
                index += 1
                continue
            if not repository:
                repository = token
            break
        repository = repository or self._git_default_push_remote(git, cwd)
        remote_url = self._git_read_value(
            git, ["remote", "get-url", "--push", repository], cwd
        )
        return remote_url or repository

    @staticmethod
    def _https_credential_target(remote_url: str) -> tuple[str, str] | None:
        parsed = urllib.parse.urlsplit(remote_url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            return None
        if port:
            host = f"{host}:{port}"
        if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host):
            return None
        clean_url = urllib.parse.urlunsplit(
            ("https", host, parsed.path or "/", "", "")
        )
        return clean_url, host

    @staticmethod
    def _reject_brokered_git_config_overrides(argv: list[str]) -> None:
        unsafe = [
            item for item in argv
            if item == "-c" or item == "--config-env" or item.startswith("--config-env=")
        ]
        if unsafe:
            raise ToolError(
                "CREDENTIAL_BROKER_ARGUMENT_BLOCKED",
                "Brokered Git HTTPS push 不允许调用方覆盖 Git 配置。",
                "permission",
                False,
                {"arguments": unsafe},
            )

    @staticmethod
    def _reject_brokered_git_env_overrides(env: dict[str, str]) -> None:
        blocked_exact = {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "CURL_CA_BUNDLE",
        }
        unsafe = sorted(
            key
            for key in env
            if key.upper().startswith(("GIT_", "GCM_", "SSH_"))
            or key.upper() in blocked_exact
        )
        if unsafe:
            raise ToolError(
                "CREDENTIAL_BROKER_ENV_BLOCKED",
                "Brokered Git HTTPS push 不允许调用方覆盖 Git、Credential、Proxy 或 TLS 环境。",
                "permission",
                False,
                {"variables": unsafe},
            )

    def _prepare_git_host_credential(
        self,
        resolved_program: str,
        argv: list[str],
        cwd: Path,
        timeout_ms: int,
        env_overrides: dict[str, str],
    ) -> _HostCredentialLaunch | None:
        if Path(resolved_program).name.lower() not in {"git", "git.exe"}:
            return None
        subcommand = self._git_subcommand(argv)
        if subcommand is None or subcommand[1] != "push":
            return None
        remote_url = self._git_push_repository(
            resolved_program, argv, subcommand[0], cwd
        )
        target = self._https_credential_target(remote_url)
        if target is None:
            return None
        target_url, target_host = target
        broker = self._host_credential_broker()
        if broker is None:
            return None
        self._reject_brokered_git_config_overrides(argv)
        self._reject_brokered_git_env_overrides(env_overrides)
        if not self._permission_granted("credential_use"):
            raise ToolError(
                "PERMISSION_REQUIRED",
                f"Git HTTPS push 需要使用宿主凭据访问 {target_host}。",
                "permission",
                False,
                {
                    "permission": "credential_use",
                    "service": "git_https",
                    "operation": "push",
                    "host": target_host,
                    "credential_exposed_to_ai": False,
                },
            )
        response = broker.prepare_host_credential(
            "git_https",
            "push",
            target_url=target_url,
            workspace=cwd,
            ttl_seconds=max(60, min(int(timeout_ms / 1000) + 30, 660)),
        )
        result = getattr(response, "result", None)
        if not getattr(response, "ok", False) or not isinstance(result, dict):
            raise ToolError(
                "HOST_CREDENTIAL_UNAVAILABLE",
                str(getattr(response, "error", "") or "Workbench Host 无法提供 Git HTTPS 凭据。"),
                "permission",
                True,
                {"service": "git_https", "host": target_host},
            )
        try:
            session_id = str(result["session_id"])
            read_root = Path(str(result["read_root"])).resolve()
            askpass_path = Path(str(result["askpass_path"])).resolve()
            askpass_path.relative_to(read_root)
        except (KeyError, OSError, ValueError) as exc:
            raise ToolError(
                "HOST_CREDENTIAL_INVALID",
                "Workbench Host Credential Session 元数据无效。",
                "permission",
            ) from exc
        if not read_root.is_dir() or not askpass_path.is_file():
            raise ToolError(
                "HOST_CREDENTIAL_INVALID",
                "Workbench Host Credential Session 文件不可用。",
                "permission",
            )
        return _HostCredentialLaunch(
            session_id=session_id,
            read_root=read_root,
            askpass_path=askpass_path,
            target_host=target_host,
        )

    @staticmethod
    def _credentialed_git_argv(argv: list[str]) -> list[str]:
        return [
            "-c", "core.hooksPath=/dev/null",
            "-c", "credential.helper=",
            "-c", "credential.interactive=never",
            "-c", "http.sslVerify=true",
            *argv,
        ]

    def _release_host_credential(self, session_id: str) -> None:
        broker = self._host_credential_broker()
        if broker is None or not session_id:
            return
        try:
            broker.release_host_credential(session_id)
        except Exception:
            pass

    def _host_credential_lock(self) -> threading.RLock:
        lock = getattr(self, "_credential_session_lock", None)
        if lock is None:
            lock = threading.RLock()
            setattr(self, "_credential_session_lock", lock)
        return lock

    def _track_host_credential(self, command: Any, session_id: str) -> None:
        sessions = getattr(self, "_host_credential_sessions", None)
        if not isinstance(sessions, dict):
            sessions = {}
            setattr(self, "_host_credential_sessions", sessions)
        with self._host_credential_lock():
            sessions[command.command_id] = session_id

        def release_when_exited() -> None:
            try:
                command.process.wait()
            finally:
                self._release_command_credential(command, force=True)

        threading.Thread(
            target=release_when_exited,
            name=f"credential-release-{command.command_id[:8]}",
            daemon=True,
        ).start()

    def _release_command_credential(self, command: Any, *, force: bool = False) -> None:
        sessions = getattr(self, "_host_credential_sessions", None)
        if not isinstance(sessions, dict):
            return
        if not force and command.process.poll() is None:
            return
        with self._host_credential_lock():
            session_id = sessions.pop(command.command_id, "")
        self._release_host_credential(session_id)

    def close_host_credentials(self) -> None:
        sessions = getattr(self, "_host_credential_sessions", None)
        if not isinstance(sessions, dict):
            return
        with self._host_credential_lock():
            values = tuple(sessions.values())
            sessions.clear()
        for session_id in values:
            self._release_host_credential(session_id)

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
        existing = next(
            (item for item in self.toolchain_registrations if item["program"] == normalized),
            None,
        )
        if existing is not None:
            resolved = self.toolchains.resolve_program(normalized)
            if resolved is None:
                raise ToolError(
                    "TOOLCHAIN_REGISTRATION_STALE",
                    f"已注册工具 {normalized} 当前不可执行，请重新确认注册。",
                    "process", False,
                )
            if self._host_tool_broker() is None:
                return resolved
            proposal = self._resolve_host_tool_proposal(normalized, cwd=cwd)
            host_executable = os.path.normcase(os.path.abspath(str(proposal["executable"])))
            if os.path.normcase(os.path.abspath(resolved)) == host_executable:
                return resolved
            return self._register_missing_toolchain(
                normalized,
                proposal=proposal,
                replace_existing=True,
            )
        local = self.toolchains.resolve_program(normalized)
        if self._host_tool_broker() is None:
            if local is not None:
                return local
            raise ToolError(
                "HOST_TOOL_RESOLUTION_REQUIRED",
                "当前连接没有 Workbench Host 工具解析通道；无法确认真实用户环境会执行哪个工具。",
                "permission", False, {"program": normalized},
            )
        proposal = self._resolve_host_tool_proposal(normalized, cwd=cwd)
        host_executable = os.path.normcase(os.path.abspath(str(proposal["executable"])))
        if local is not None and os.path.normcase(os.path.abspath(local)) == host_executable:
            return local
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
                reason=(f"AI 准备在当前 Workspace 使用 {program}。Workbench Host 已通过真实用户环境命令解析出工具路径；"
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
        credential = self._prepare_git_host_credential(
            resolved_program, argv, cwd, timeout_ms, env_overrides
        )
        launch_argv = self._credentialed_git_argv(argv) if credential else argv
        try:
            command = self._process_launch_command(resolved_program, launch_argv)
            command = self.process_sandbox.wrap(
                command,
                cwd=cwd,
                permissions=ACTIVE_PERMISSIONS.get(),
                readable_roots=((credential.read_root,) if credential else ()),
            )
            process_env = self._command_env(env_overrides)
            if credential:
                process_env.update(
                    {
                        "GIT_ASKPASS": str(credential.askpass_path),
                        "GIT_TERMINAL_PROMPT": "0",
                        "GIT_CONFIG_SYSTEM": os.devnull,
                        "GCM_INTERACTIVE": "Never",
                    }
                )
            managed = self.commands.start(
                command,
                cwd=cwd,
                env=process_env,
                stdin_text=str(args.get("stdin", "")),
                timeout_ms=timeout_ms,
                tty=bool(args.get("tty", False)),
                shell=False,
            )
        except Exception:
            if credential:
                self._release_host_credential(credential.session_id)
            raise
        if credential:
            self._track_host_credential(managed, credential.session_id)
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        self._release_command_credential(managed)
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
        managed = self.commands.write(
            str(args["command_id"]), str(args.get("chars", ""))
        )
        self.commands.wait(managed, int(args.get("yield_time_ms", 10_000)))
        self._release_command_credential(managed)
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
        self._release_command_credential(managed, force=True)
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
        self._release_command_credential(command)
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
