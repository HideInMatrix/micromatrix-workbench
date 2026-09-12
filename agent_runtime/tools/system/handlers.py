from __future__ import annotations

import os
from typing import Any
from ...core.constants import ENDPOINT_PATH, SERVER_NAME, SERVER_TITLE
from ...errors import ToolError
from ...permissions.capabilities import ELICITABLE_PERMISSIONS
from ...processes import STREAM_HEAD_BYTES, STREAM_LIMIT_BYTES
from ...protocol import KNOWN_PROTOCOL_VERSIONS


class SystemHandlers:
    """Server introspection, environment diagnostics and permission tool handlers."""

    def _host_client(self) -> Any | None:
        broker = self.local_permission_broker
        return broker if broker is not None else None

    def host_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        client = self._host_client()
        status = getattr(client, "host_status", None) if client is not None else None
        if not callable(status):
            return {
                "contract_version": 2,
                "supported": False,
                "configured": False,
                "connection": {
                    "state": "disconnected",
                    "host_instance_id": "",
                    "generation": None,
                    "worker_pid": None,
                    "worker_alive": False,
                    "last_seen_ms": None,
                    "heartbeat_age_ms": None,
                },
                "invocation": {
                    "state": "unavailable",
                    "reasons": [{"code": "HOST_NOT_CONFIGURED"}],
                },
                "ok": True,
            }
        return dict(status())

    def host_reconnect(self, _args: dict[str, Any]) -> dict[str, Any]:
        client = self._host_client()
        reconnect = getattr(client, "host_reconnect", None) if client is not None else None
        if not callable(reconnect):
            return {**self.host_status({}), "reconnected": False}
        return dict(reconnect())

    def host_diagnostics(self, args: dict[str, Any]) -> dict[str, Any]:
        client = self._host_client()
        diagnostics = getattr(client, "host_diagnostics", None) if client is not None else None
        if not callable(diagnostics):
            return {
                "status": self.host_status({}),
                "supervisor": {},
                "providers": [],
                "active": [],
                "events": [],
                "ok": True,
            }
        try:
            return dict(diagnostics(max_events=int(args.get("max_events", 20))))
        except Exception as exc:
            return {
                "status": self.host_status({}),
                "supervisor": {},
                "providers": [],
                "active": [],
                "events": [],
                "partial": True,
                "errors": [{"source": "diagnostics", "error": type(exc).__name__}],
                "ok": True,
            }

    def host_restart(self, _args: dict[str, Any]) -> dict[str, Any]:
        if not self._permission_granted("host_manage"):
            raise ToolError(
                "PERMISSION_REQUIRED",
                "重启 Workbench Desktop Host Worker 需要独立的 Host 管理授权。",
                "permission",
                False,
                {"permission": "host_manage", "scope": "workbench_owned_host_worker"},
            )
        client = self._host_client()
        restart = getattr(client, "host_restart", None) if client is not None else None
        if not callable(restart):
            raise ToolError(
                "HOST_DISCONNECTED",
                "当前 Runtime 未连接 Desktop Host Supervisor。",
                "runtime",
                True,
                {"stage": "preflight", "cause_code": "HOST_NOT_CONFIGURED"},
            )
        result = dict(restart())
        if not result.get("ok"):
            raise ToolError(
                str(result.get("cause_code") or "HOST_RESTART_FAILED"),
                str(result.get("error") or "Host Worker restart failed."),
                "runtime",
                True,
                {"request_id": result.get("request_id")},
            )
        return result

    def server_info(self, args: dict[str, Any]) -> dict[str, Any]:
        tools = [definition.name for definition in self._tools]
        mcp_tools = [definition.name for definition in self._tools]
        host = self.host_status({})
        connection = host.get("connection") if isinstance(host, dict) else {}
        summary: dict[str, Any] = {
            "server": SERVER_NAME,
            "title": SERVER_TITLE,
            "version": self.server_identity()["version"],
            "contract_version": 2,
            "contract_revision": self.tool_contract_revision,
            "workspace": str(self.workspace.root),
            "permission_mode": self.permission_mode,
            "auth_enabled": self.auth_enabled(),
            "supported_protocol_versions": list(KNOWN_PROTOCOL_VERSIONS),
            "endpoint_path": ENDPOINT_PATH,
            "tool_count": len(tools),
            "host": {
                "supported": bool(host.get("supported", False)) if isinstance(host, dict) else False,
                "configured": bool(host.get("configured", False)) if isinstance(host, dict) else False,
                "connection": {
                    "state": str((connection or {}).get("state") or "disconnected")
                    if isinstance(connection, dict)
                    else "disconnected",
                    "generation": (connection or {}).get("generation")
                    if isinstance(connection, dict)
                    else None,
                },
                "health_revision": host.get("health_revision") if isinstance(host, dict) else None,
            },
            "available_sections": ["permissions", "execution", "toolchains", "project", "tools"],
        }
        requested_sections = args.get("sections")
        if not isinstance(requested_sections, list) or not requested_sections:
            return summary
        project_tool_contexts = {
            kind: self.toolchains.project_context(program, self.workspace.root)
            for kind, program in (("node", "node"), ("python", "python3"), ("go", "go"))
        }
        details = {
            "server": SERVER_NAME,
            "title": SERVER_TITLE,
            "version": __version__,
            "workspace": str(self.workspace.root),
            "permission_mode": self.permission_mode,
            "permission_profile": {
                "name": self.permission_profile.name,
                "capabilities": sorted(
                    capability.value
                    for capability in self.permission_profile.capabilities
                ),
                "auto_granted_operations": sorted(
                    permission.value
                    for permission in self.permission_profile.auto_granted_operations
                ),
            },
            "permission_session": {
                "scope": "runtime_profile",
                "principal_isolated": True,
                "request_state_single_use": True,
                "grant_argument_bound": True,
                "desktop_broker": {
                    "configured": self.permission_session.broker_client is not None,
                    "priority": "desktop_first",
                },
                "host_tool_resolution": {
                    "configured": callable(
                        getattr(self.local_permission_broker, "resolve_host_tool", None)
                    ),
                    "strategy": "workspace_aware_desktop_host_command",
                    "project_context": "workspace_metadata_fingerprint",
                    "host_environment_exposed_to_ai": False,
                },
                "host_capabilities": {
                    "configured": callable(
                        getattr(self.local_permission_broker, "invoke_host_capability", None)
                    ),
                    "model": "desktop_host_session",
                    "runtime_process_launch": False,
                    "execution_plane": "host_process_supervisor",
                    "application_resolution": "os_registration",
                    "tool_specific_process_adapters": False,
                },
                "host_identity_execution": {
                    "configured": callable(
                        getattr(self.local_permission_broker, "invoke_host_identity", None)
                    ),
                    "model": "exact_invocation_host_identity",
                    "tool_specific_adapters": False,
                    "host_environment_exposed_to_ai": False,
                    "permission": "host_identity_use",
                    "public_api": "exec_process(use_host_identity=true)",
                },
            },
            "auth_enabled": self.auth_enabled(),
            "supported_protocol_versions": list(KNOWN_PROTOCOL_VERSIONS),
            "endpoint_path": ENDPOINT_PATH,
            "runtime_dir": str(self.commands.runtime_dir),
            "home": str(self.commands.home_dir),
            "config_dir": str(self.commands.config_dir),
            "tmpdir": str(self.commands.tmp_dir),
            "cache_dir": str(self.commands.cache_dir),
            "network_allowed": self.allow_network,
            "dangerously_skip_all_permissions": self.permission_mode == "dangerous",
            "annotation_override": (
                "fake_readonly" if self.fake_readonly_annotations else None
            ),
            "landlock": {
                "available": False,
                "enabled": False,
                "abi_version": None,
                "reason": "Landlock compatibility field; process isolation is reported in sandbox.",
                "details": {},
            },
            "sandbox": self.sandbox_profile.to_dict(),
            "exec_policy": {
                "shell_expansion": (
                    "allowed"
                    if self.permission_mode == "dangerous"
                    else "restricted"
                    if self.permission_mode == "trusted"
                    else "blocked"
                ),
                "inline_script": (
                    "allowed" if self.permission_mode != "safe" or (
                        self.sandbox_profile.filesystem_isolation
                        and self.sandbox_profile.network_isolation) else "approval_required"
                ),
                "secret_env_filter": self.permission_mode != "dangerous",
                "global_tmp_write": (
                    "allowed" if self.permission_mode == "dangerous" else "blocked"
                ),
            },
            "shell_env_inherit": (
                "sanitized" if self.permission_mode != "dangerous" else "full"
            ),
            "shell_env_include_only": (
                [
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
                ]
                if self.permission_mode != "dangerous"
                else []
            ),
            "shell_env_exclude": [],
            "safe_exec_path": list(self.safe_exec_path),
            "toolchains": self._toolchain_snapshot.get("toolchains", {}),
            "project_tool_contexts": project_tool_contexts,
            "registered_toolchains": list(self.toolchain_registrations),
            "output_retention": {
                "buffer_bytes_per_stream": STREAM_LIMIT_BYTES,
                "head_bytes_per_stream": STREAM_HEAD_BYTES,
            },
            "project_context": {
                "root_instruction_files": [
                    item.path for item in self.project_context.root_files
                ],
                "nested_instruction_files": list(self.project_context.nested_files),
                "warnings": list(self.project_context.warnings),
            },
            "tools": tools,
            "mcp_tools": mcp_tools,
            "tool_capabilities": {
                definition.name: sorted(
                    capability.value for capability in definition.capabilities
                )
                for definition in self._tools
            },
            "tool_execution_kinds": {
                definition.name: definition.execution_kind.value
                for definition in self._tools
            },
            "tool_count": len(tools),
            "mcp_tool_count": len(mcp_tools),
        }
        section_payloads = {
            "permissions": {
                "permission_profile": details["permission_profile"],
                "permission_session": details["permission_session"],
            },
            "execution": {
                key: details[key]
                for key in (
                    "sandbox",
                    "exec_policy",
                    "shell_env_inherit",
                    "shell_env_include_only",
                    "shell_env_exclude",
                    "network_allowed",
                    "dangerously_skip_all_permissions",
                    "annotation_override",
                    "output_retention",
                )
            },
            "toolchains": {
                "safe_exec_path": details["safe_exec_path"],
                "toolchains": details["toolchains"],
                "project_tool_contexts": details["project_tool_contexts"],
                "registered_toolchains": details["registered_toolchains"],
            },
            "project": {"project_context": details["project_context"]},
            "tools": {
                "tools": details["tools"],
                "tool_capabilities": details["tool_capabilities"],
                "tool_execution_kinds": details["tool_execution_kinds"],
                "tool_count": details["tool_count"],
            },
        }
        summary["sections"] = {
            section: section_payloads[section]
            for section in requested_sections
            if section in section_payloads
        }
        return summary

    def check_exec_environment(self, _args: dict[str, Any]) -> dict[str, Any]:
        warnings = []
        project_tool_contexts = {
            kind: self.toolchains.project_context(program, self.workspace.root)
            for kind, program in (("node", "node"), ("python", "python3"), ("go", "go"))
        }
        if not self.sandbox_profile.os_kernel_sandbox:
            warnings.append(
                "OS-kernel process confinement is not enforced yet; capability policy, workspace guards, sanitized environment, and offline hints provide defense in depth."
            )
            if self.sandbox_profile.backend_reason:
                warnings.append(self.sandbox_profile.backend_reason)
        else:
            if not self.sandbox_profile.filesystem_isolation:
                warnings.append(
                    "OS process isolation is enabled, but filesystem confinement is not enforced by the active backend."
                )
            if not self.sandbox_profile.network_isolation:
                warnings.append(
                    "OS process isolation is enabled, but network confinement is not enforced by the active backend."
                )
        if self.permission_mode == "dangerous":
            warnings.append("permission_mode=dangerous disables MCP safety gates")
        return {
            "workspace": str(self.workspace.root),
            "permission_mode": self.permission_mode,
            "network_allowed": self.allow_network,
            "runtime_dir": str(self.commands.runtime_dir),
            "home": str(self.commands.home_dir),
            "config_dir": str(self.commands.config_dir),
            "tmpdir": str(self.commands.tmp_dir),
            "cache_dir": str(self.commands.cache_dir),
            "landlock_enabled": False,
            "landlock_abi": None,
            "global_tmp_write": (
                "allowed" if self.permission_mode == "dangerous" else "blocked"
            ),
            "effective_path": (
                list(self.safe_exec_path)
                if self.permission_mode != "dangerous"
                else os.environ.get("PATH", "").split(os.pathsep)
            ),
            "toolchains": self._toolchain_snapshot.get("toolchains", {}),
            "project_tool_contexts": project_tool_contexts,
            "registered_toolchains": list(self.toolchain_registrations),
            "warnings": warnings,
            "sandbox": self.sandbox_profile.to_dict(),
        }

    def request_permissions(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.permission_mode == "dangerous":
            return {
                "ok": True,
                "status": "granted",
                "grant_id": "dangerously-skip-all-permissions",
                "expires_at": None,
                "constraints": {
                    "mode": "dangerously_skip_all_permissions",
                    "workspace": str(self.workspace.root),
                    "requested": args,
                },
                "warnings": [
                    "permission_mode=dangerous is enabled; permission-gated operations are auto-granted"
                ],
            }
        permission = str(args.get("permission") or "")
        if permission not in ELICITABLE_PERMISSIONS:
            return {
                "ok": False,
                "status": "unsupported",
                "grant_id": None,
                "expires_at": None,
                "error": {
                    "code": "PERMISSION_NOT_ELICITABLE",
                    "message": "该权限不能通过临时用户授权提升，请修改 Server 权限模式或配置。",
                    "category": "permission",
                    "retryable": False,
                    "details": {"permission": permission},
                },
            }
        if permission == "host_identity_use" and str(args.get("scope") or "once") != "once":
            return {
                "ok": False,
                "status": "unsupported_scope",
                "grant_id": None,
                "expires_at": None,
                "error": {
                    "code": "HOST_IDENTITY_SCOPE_INVALID",
                    "message": "host_identity_use 只能授权当前完全相同的单次调用。",
                    "category": "permission",
                    "retryable": False,
                    "details": {"permission": permission, "allowed_scope": "once"},
                },
            }
        raise ToolError(
            "PERMISSION_REQUIRED",
            str(args.get("reason") or "该操作需要用户临时授权。"),
            "permission",
            False,
            {"permission": permission, "requested": dict(args)},
        )
