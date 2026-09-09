from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..permissions.context import ACTIVE_PERMISSIONS


class HostIdentityRuntimeClient:
    """Runtime-side bridge for exact-invocation Desktop Host identity execution."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    @staticmethod
    def is_command_id(command_id: str) -> bool:
        return bool(re.fullmatch(r"host_[A-Za-z0-9_-]{8,128}", command_id))

    def _broker(self) -> Any:
        broker = self.runtime.local_permission_broker
        if not callable(getattr(broker, "invoke_host_identity", None)):
            raise ToolError(
                "HOST_IDENTITY_UNAVAILABLE",
                "当前连接没有 Desktop Host identity execution 通道。",
                "permission",
                False,
            )
        return broker

    def _registration(self, executable: str) -> dict[str, Any]:
        normalized = os.path.normcase(os.path.abspath(executable))
        for registration in self.runtime.toolchain_registrations:
            candidate = os.path.normcase(os.path.abspath(str(registration["executable"])))
            if candidate == normalized:
                return dict(registration)
        raise ToolError(
            "HOST_IDENTITY_REGISTRATION_REQUIRED",
            "Host identity execution 只允许已由 Desktop Host 确认并注册的 Runtime executable。",
            "permission",
            False,
            {"executable": executable},
        )

    def invoke(
        self,
        action: str,
        *,
        command_id: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._broker().invoke_host_identity(
            action,
            command_id=command_id,
            parameters=dict(parameters or {}),
        )
        result = getattr(response, "result", None)
        if not getattr(response, "ok", False) or not isinstance(result, dict):
            raise ToolError(
                "HOST_IDENTITY_FAILED",
                str(getattr(response, "error", "") or "Desktop Host identity execution 失败。"),
                "process",
                True,
            )
        return dict(result)

    def start(
        self,
        *,
        executable: str,
        argv: list[str],
        cwd: Path,
        env_overrides: dict[str, str],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if env_overrides:
            raise ToolError(
                "HOST_IDENTITY_ENV_OVERRIDE_BLOCKED",
                "Host identity execution 使用真实宿主用户环境，不接受调用方 env override。",
                "permission",
                False,
                {"variables": sorted(env_overrides)},
            )
        if not self.runtime._permission_granted("host_identity_use"):
            raise ToolError(
                "PERMISSION_REQUIRED",
                "该调用请求在 Desktop Host 用户身份上下文中执行已确认的 Runtime executable。",
                "permission",
                False,
                {
                    "permission": "host_identity_use",
                    "executable": executable,
                    "workspace": str(self.runtime.workspace.root),
                    "host_environment_exposed_to_ai": False,
                    "scope": "exact_invocation_once",
                },
            )
        workspace = self.runtime.workspace.root.resolve()
        protected_paths: list[str] = []
        for raw in self.runtime.sandbox_profile.protected_ro:
            path = Path(raw).resolve()
            try:
                path.relative_to(workspace)
            except ValueError:
                continue
            protected_paths.append(str(path))
        result = self.invoke(
            "start",
            parameters={
                "executable": executable,
                "argv": argv,
                "cwd": str(cwd),
                "workspace": str(self.runtime.workspace.root),
                "registration": self._registration(executable),
                "protected_paths": protected_paths,
                "env": env_overrides,
                "stdin": str(args.get("stdin", "")),
                "timeout_ms": int(args.get("timeout_ms", 30_000)),
                "yield_time_ms": int(args.get("yield_time_ms", 10_000)),
                "tty": bool(args.get("tty", False)),
                "max_output_bytes": int(args.get("max_output_bytes", 65_536)),
                "network_allowed": bool(
                    self.runtime.allow_network or self.runtime._permission_granted("network")
                ),
                "permissions": sorted(ACTIVE_PERMISSIONS.get()),
            },
        )
        result["program"] = executable
        result["argv"] = argv
        result["shell"] = False
        return result
