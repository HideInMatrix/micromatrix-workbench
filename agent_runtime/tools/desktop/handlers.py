from __future__ import annotations

import hashlib
from typing import Any

from ...errors import ToolError
from ...protocol import current_request_context
from .._shared import decode_png_base64
from .models import DesktopAction


class DesktopHandlers:
    _MUTATING_ACTIONS = frozenset(
        {
            DesktopAction.CLICK.value,
            DesktopAction.TYPE.value,
            DesktopAction.KEYPRESS.value,
            DesktopAction.SCROLL.value,
            DesktopAction.DRAG.value,
        }
    )

    def _desktop_call(
        self,
        action: str,
        *,
        session_id: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        broker = self.local_permission_broker
        invoke = getattr(broker, "invoke_host_capability", None) if broker is not None else None
        if not callable(invoke):
            raise ToolError(
                "HOST_DISCONNECTED",
                "当前 Runtime 未连接 Workbench Desktop Host Capability 通道。",
                "runtime",
                True,
                {
                    "capability": "desktop",
                    "action": action,
                    "stage": "preflight",
                    "cause_code": "HOST_NOT_CONFIGURED",
                    "request_id": None,
                    "generation": None,
                    "action_state": "not_started" if action in self._MUTATING_ACTIONS else None,
                },
            )
        status_reader = getattr(broker, "host_status", None)
        if callable(status_reader):
            host = status_reader()
            connection = host.get("connection") if isinstance(host, dict) else None
            if isinstance(connection, dict) and connection.get("state") == "disconnected":
                raise ToolError(
                    "HOST_DISCONNECTED",
                    "Workbench Desktop Host 当前离线。",
                    "runtime",
                    True,
                    {
                        "capability": "desktop",
                        "action": action,
                        "stage": "preflight",
                        "cause_code": "HOST_DISCONNECTED",
                        "request_id": None,
                        "generation": connection.get("generation"),
                        "action_state": "not_started" if action in self._MUTATING_ACTIONS else None,
                    },
                )
        context = current_request_context()
        principal = context.principal if context and context.principal else "anonymous"
        host_parameters = dict(parameters or {})
        host_parameters["_principal_hash"] = hashlib.sha256(
            principal.encode("utf-8", "surrogateescape")
        ).hexdigest()
        response = invoke(
            "desktop",
            action,
            parameters=host_parameters,
            session_id=session_id,
        )
        if not getattr(response, "ok", False) or not isinstance(getattr(response, "result", None), dict):
            status = str(getattr(response, "status", "error") or "error")
            details = dict(getattr(response, "details", None) or {})
            cause_code = str(details.get("cause_code") or "HOST_CAPABILITY_FAILED")
            public_code = {
                "HOST_HEALTH_STALE": "HOST_DISCONNECTED",
                "HOST_DISCONNECTED": "HOST_DISCONNECTED",
                "HOST_ACK_TIMEOUT": "HOST_ACK_TIMEOUT",
                "HOST_PROTOCOL_MISMATCH": "HOST_PROTOCOL_MISMATCH",
                "SESSION_EXPIRED": "SESSION_EXPIRED",
            }.get(cause_code, cause_code)
            if action in self._MUTATING_ACTIONS:
                if details.get("host_ack_at_ms") is None:
                    details["action_state"] = "not_started"
                elif str(details.get("stage") or "") in {"execute", "response", "provider"} and public_code in {
                    "HOST_DISCONNECTED",
                    "HOST_ACK_TIMEOUT",
                    "HOST_RESPONSE_TIMEOUT",
                    "HOST_GENERATION_CHANGED",
                }:
                    details["action_state"] = "unknown"
                else:
                    details["action_state"] = "failed"
            details.update({"capability": "desktop", "action": action, "status": status})
            raise ToolError(
                public_code,
                str(getattr(response, "error", "") or "Desktop Host Capability 操作失败。"),
                "runtime",
                status in {"timeout", "ack_timeout", "unavailable"},
                details,
            )
        return dict(response.result)

    @staticmethod
    def _attach_observation_image(payload: dict[str, Any]) -> dict[str, Any]:
        observation = payload if "data_base64" in payload else payload.get("observation")
        if not isinstance(observation, dict):
            return payload
        encoded = str(observation.pop("data_base64", "") or "")
        if not encoded:
            return payload
        data = decode_png_base64(encoded, label="Desktop observation")
        observation.setdefault("mime_type", "image/png")
        observation["bytes"] = len(data)
        payload["_image"] = ("image/png", encoded)
        return payload

    def desktop_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args["action"])
        if action in {DesktopAction.TARGETS.value, DesktopAction.DETACH.value}:
            return {}
        session_id = str(args.get("session_id") or "")
        parameters = {
            key: value
            for key, value in args.items()
            if key not in {"action", "session_id"}
        }
        parameters["_preflight"] = True
        return self._desktop_call(
            action,
            session_id=session_id,
            parameters=parameters,
        )

    def desktop(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args["action"])
        session_id = str(args.get("session_id") or "")
        parameters = {
            key: value
            for key, value in args.items()
            if key not in {"action", "session_id"}
        }
        payload = self._desktop_call(
            action,
            session_id=session_id,
            parameters=parameters,
        )
        if action == DesktopAction.DETACH.value and bool(payload.get("detached")):
            self.permission_session.revoke_desktop_session_permissions(
                current_request_context(),
                session_id,
            )
        if action == DesktopAction.OBSERVE.value or action in self._MUTATING_ACTIONS:
            return self._attach_observation_image(payload)
        return payload


__all__ = ["DesktopHandlers"]
