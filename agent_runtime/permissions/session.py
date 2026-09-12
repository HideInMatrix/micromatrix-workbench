"""Permission lifecycle for a single MCP Runtime/Profile session."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..errors import RpcError
from ..local_permission_broker import LocalPermissionDecision, redact_for_display
from ..protocol import RequestContext
from .broker import PermissionBroker
from .capabilities import ELICITABLE_PERMISSIONS
from .grants import PermissionGrantStore
from .state import PermissionStateStore


class PermissionSession:
    def __init__(
        self,
        workspace: Path,
        *,
        broker_client: Any | None = None,
        load_broker_from_env: bool = True,
    ) -> None:
        self.state = PermissionStateStore(workspace)
        self.grants = PermissionGrantStore()
        self.broker = (
            PermissionBroker.from_env()
            if broker_client is None and load_broker_from_env
            else PermissionBroker(broker_client)
        )

    @property
    def broker_client(self) -> Any | None:
        return self.broker.client

    @broker_client.setter
    def broker_client(self, value: Any | None) -> None:
        self.broker.client = value

    def store_grant(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        permission: str,
        principal: str,
        scope: str,
        ttl_seconds: int,
    ) -> tuple[str, int]:
        return self.grants.store(
            tool_name=tool_name,
            arguments=arguments,
            permission=permission,
            principal=principal,
            scope=scope,
            ttl_seconds=ttl_seconds,
        )

    def stored_permissions_for_call(
        self,
        name: str,
        arguments: dict[str, Any],
        context: RequestContext | None,
    ) -> frozenset[str]:
        if context is None:
            return frozenset()
        return self.grants.permissions_for_call(
            name,
            arguments,
            context.principal,
        )

    def session_permissions_for_call(
        self,
        context: RequestContext | None,
    ) -> frozenset[str]:
        principal = context.principal if context and context.principal else "anonymous"
        return self.grants.session_permissions(principal)

    def grant_session_permissions(self, context: RequestContext | None) -> None:
        principal = context.principal if context and context.principal else "anonymous"
        self.grants.grant_session(principal)

    def grant_resource_session_permission(
        self,
        context: RequestContext | None,
        resource_type: str,
        resource_id: str,
        permission: str,
    ) -> None:
        principal = context.principal if context and context.principal else "anonymous"
        self.grants.grant_resource_session(
            principal,
            resource_type,
            resource_id,
            permission,
        )

    @staticmethod
    def authorization_session_identity(
        permission_context: dict[str, Any] | None,
    ) -> tuple[str, str] | None:
        if not isinstance(permission_context, dict):
            return None
        authorization_session = permission_context.get("authorization_session")
        if not isinstance(authorization_session, dict):
            return None
        resource_type = str(authorization_session.get("type") or "").strip()
        resource_id = str(authorization_session.get("id") or "").strip()
        if not resource_type or not resource_id:
            return None
        return resource_type, resource_id

    @staticmethod
    def authorization_session_creation_type(
        permission_context: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(permission_context, dict):
            return None
        authorization_session = permission_context.get("authorization_session")
        if not isinstance(authorization_session, dict):
            return None
        if authorization_session.get("create") is not True:
            return None
        resource_type = str(authorization_session.get("type") or "").strip()
        return resource_type or None

    def resource_session_permissions_for_call(
        self,
        permission_context: dict[str, Any] | None,
        context: RequestContext | None,
    ) -> frozenset[str]:
        identity = self.authorization_session_identity(permission_context)
        if identity is None:
            return frozenset()
        resource_type, resource_id = identity
        principal = context.principal if context and context.principal else "anonymous"
        return self.grants.resource_session_permissions(
            principal,
            resource_type,
            resource_id,
        )

    def revoke_resource_session_permissions(
        self,
        context: RequestContext | None,
        resource_type: str,
        resource_id: str,
    ) -> None:
        principal = context.principal if context and context.principal else "anonymous"
        self.grants.revoke_resource_session(principal, resource_type, resource_id)

    def permission_round(
        self,
        name: str,
        arguments: dict[str, Any],
        context: RequestContext | None,
    ) -> tuple[frozenset[str], bool]:
        if context is None or context.request_state is None:
            if context and context.input_responses and "permission" in context.input_responses:
                raise RpcError(
                    -32602,
                    "Permission inputResponses require a matching requestState",
                    {"reason": "permission_response_without_state"},
                )
            return frozenset(), False

        state = self.state.verify(
            context.request_state,
            name=name,
            arguments=arguments,
            principal=context.principal,
        )
        responses = context.input_responses or {}
        response = responses.get("permission")
        if not isinstance(response, dict):
            raise RpcError(
                -32602,
                "Permission requestState requires inputResponses.permission",
                {"reason": "permission_response_missing"},
            )
        self.state.consume(
            context.request_state,
            int(state.get("exp", 0)),
        )
        raw_granted = state.get("granted")
        granted = {
            str(item)
            for item in raw_granted
            if isinstance(raw_granted, list) and isinstance(item, str)
        } if isinstance(raw_granted, list) else set()
        action = response.get("action")
        content = response.get("content")
        confirmed = isinstance(content, dict) and content.get("confirm") is True
        if action != "accept" or not confirmed:
            return frozenset(granted), True
        granted.add(str(state["permission"]))
        return frozenset(granted), False

    @staticmethod
    def supports_elicitation(context: RequestContext | None) -> bool:
        if context is None or context.era != "modern":
            return False
        capabilities = context.client_capabilities
        if not isinstance(capabilities, Mapping):
            return False
        elicitation = capabilities.get("elicitation")
        if not isinstance(elicitation, Mapping):
            return False
        if not elicitation:
            return True
        return isinstance(elicitation.get("form"), Mapping)

    @staticmethod
    def permission_message(
        permission: str,
        name: str,
        arguments: dict[str, Any],
        fallback: str,
    ) -> str:
        descriptions = {
            "network": "该操作需要访问网络。",
            "destructive_command": "该操作包含潜在破坏性的 Workspace 命令。",
            "git_metadata_write": "该操作需要写入当前 Workspace 的 .git 元数据。",
            "long_timeout": "该操作需要超过 Safe 模式默认上限的执行时间。",
            "sensitive_env": "该操作需要向子进程传入敏感环境变量。",
            "shell_expansion": "该操作需要启用受限制的 Shell 展开能力。",
            "inline_script": "该操作需要执行内联脚本。",
            "privileged_executable": "启动用户配置的外部 stdio MCP 进程；此授权不改变任务工具链的 PATH 或沙箱读取范围。",
            "browser_observe": "观察由 Workbench Desktop Host 托管的隔离浏览器会话并读取页面截图/结构化页面信息；不会授予点击、输入或导航权限。",
            "browser_control": "启动并控制由 Workbench Desktop Host 托管的隔离浏览器会话；不会复用用户日常浏览器 Profile。",
            "desktop_observe": "观察已明确绑定的桌面应用窗口并读取窗口截图/可用辅助功能信息；不会授予鼠标或键盘控制权限。",
            "desktop_control": "控制已明确绑定的桌面应用窗口，包括鼠标、键盘、滚动或拖拽；不会授权其他未绑定应用或窗口。",
            "application_launch": "启动或激活已通过 Desktop Host 解析并绑定身份指纹的桌面应用；不会授权其他应用。",
            "application_control": "请求退出已通过 Desktop Host 解析并绑定身份指纹的桌面应用；可能影响未保存内容。",
            "host_artifact_read": "读取外部应用在宿主用户临时目录生成的单个受限产物；不会授予任意 Host 文件读取能力。",
            "host_identity_use": "允许当前完全相同的结构化进程调用使用 Desktop Host 用户身份上下文；Host 环境和凭据不会作为 Tool Result 返回给 AI。",
            "host_manage": "允许重启 Workbench 自有的 Desktop Host Worker；不会操作任意系统进程或用户应用。",
        }
        try:
            rendered = json.dumps(
                redact_for_display(arguments),
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError):
            rendered = str(arguments)
        if len(rendered) > 700:
            rendered = rendered[:697] + "..."
        return (
            f"{descriptions.get(permission, fallback)}\n"
            f"工具：{name}\n"
            f"参数：{rendered}\n"
            "仅授权这一次完全相同的工具调用，是否允许？"
        )

    def input_required(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        display_arguments: dict[str, Any] | None = None,
        permission: str,
        message: str,
        context: RequestContext | None,
        granted: frozenset[str],
    ) -> dict[str, Any] | None:
        if permission not in ELICITABLE_PERMISSIONS:
            return None
        if not self.supports_elicitation(context):
            return None
        assert context is not None
        return {
            "resultType": "input_required",
            "inputRequests": {
                "permission": {
                    "method": "elicitation/create",
                    "params": {
                        "mode": "form",
                        "message": self.permission_message(
                            permission,
                            name,
                            display_arguments or arguments,
                            message,
                        ),
                        "requestedSchema": {
                            "type": "object",
                            "properties": {
                                "confirm": {
                                    "type": "boolean",
                                    "title": "允许本次操作",
                                    "description": "仅授权当前完全相同的工具调用。",
                                    "default": False,
                                }
                            },
                            "required": ["confirm"],
                        },
                    },
                }
            },
            "requestState": self.state.mint(
                name=name,
                arguments=arguments,
                permission=permission,
                principal=context.principal,
                granted=granted,
            ),
        }

    def request_local_permission(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        display_arguments: dict[str, Any] | None = None,
        permission: str,
        message: str,
        context: RequestContext | None,
    ) -> LocalPermissionDecision:
        if permission not in ELICITABLE_PERMISSIONS:
            return LocalPermissionDecision("unavailable")
        return self.broker.request(
            name=name,
            arguments=arguments,
            display_arguments=display_arguments,
            permission=permission,
            message=message,
            principal=context.principal if context else "anonymous",
        )

