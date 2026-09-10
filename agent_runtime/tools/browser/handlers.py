from __future__ import annotations

import base64
import binascii
from typing import Any

from ...errors import ToolError
from ...permissions.capabilities import Capability


class BrowserHandlers:
    _MUTATING_ACTIONS = frozenset({"open", "navigate", "click", "fill", "press"})

    def _browser_permission_required(self, permission: str) -> None:
        if self._permission_granted(permission):
            return
        if permission == "browser_observe":
            message = "需要观察 Workbench Desktop Host 托管的隔离浏览器会话。"
        else:
            message = "需要启动或控制 Workbench Desktop Host 托管的隔离浏览器会话。"
        raise ToolError(
            "PERMISSION_REQUIRED",
            message,
            "permission",
            False,
            {
                "permission": permission,
                "host_managed": True,
                "isolated_profile": True,
            },
        )

    def _browser_call(
        self,
        action: str,
        *,
        session_id: str = "",
        parameters: dict[str, Any] | None = None,
        permission: str | None = "browser_control",
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
                    "capability": "browser",
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
                        "capability": "browser",
                        "action": action,
                        "stage": "preflight",
                        "cause_code": "HOST_DISCONNECTED",
                        "request_id": None,
                        "generation": connection.get("generation"),
                        "action_state": "not_started" if action in self._MUTATING_ACTIONS else None,
                    },
                )
        if permission:
            self._browser_permission_required(permission)
        response = invoke(
            "browser",
            action,
            parameters=dict(parameters or {}),
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
                elif str(details.get("stage") or "") in {"execute", "response"} and public_code in {
                    "HOST_DISCONNECTED",
                    "HOST_ACK_TIMEOUT",
                    "HOST_RESPONSE_TIMEOUT",
                    "HOST_GENERATION_CHANGED",
                }:
                    details["action_state"] = "unknown"
                else:
                    details["action_state"] = "failed"
            details.update({"capability": "browser", "action": action, "status": status})
            raise ToolError(
                public_code,
                str(getattr(response, "error", "") or "Browser Host Capability 操作失败。"),
                "runtime",
                status in {"timeout", "ack_timeout", "unavailable"},
                details,
            )
        return dict(response.result)

    @staticmethod
    def _post_observe_parameters(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "observe_after": bool(args.get("observe_after", True)),
            "max_text": int(args.get("max_text", 12_000)),
            "max_elements": int(args.get("max_elements", 300)),
        }

    def _attach_post_observation_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        observation = payload.get("observation")
        if not isinstance(observation, dict):
            return payload
        encoded = str(observation.pop("data_base64", "") or "")
        if not encoded:
            return payload
        data = self._decode_image(encoded)
        if len(data) > 25 * 1024 * 1024:
            raise ToolError("OUTPUT_TOO_LARGE", "Browser observation screenshot 超过 25 MiB 限制。", "runtime")
        observation.setdefault("mime_type", "image/png")
        observation["bytes"] = len(data)
        payload["_image"] = ("image/png", encoded)
        return payload

    def browser_open(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call("open", parameters={
            "url": str(args.get("url") or "about:blank"),
            "headless": bool(args.get("headless", True)),
            "width": int(args.get("width", 1440)),
            "height": int(args.get("height", 900)),
            **self._post_observe_parameters(args),
        })
        return self._attach_post_observation_image(payload)

    def browser_navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "navigate",
            session_id=str(args["session_id"]),
            parameters={
                "url": str(args["url"]),
                **self._post_observe_parameters(args),
            },
        )
        return self._attach_post_observation_image(payload)

    def browser_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "snapshot",
            session_id=str(args["session_id"]),
            parameters={
                "max_text": int(args.get("max_text", 12_000)),
                "max_elements": int(args.get("max_elements", 300)),
            },
            permission="browser_observe",
        )
        return self._attach_image(payload)

    def browser_click(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "click",
            session_id=str(args["session_id"]),
            parameters={
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
                "observation_id": str(args.get("observation_id") or ""),
                **self._post_observe_parameters(args),
            },
        )
        return self._attach_post_observation_image(payload)

    def browser_fill(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "fill",
            session_id=str(args["session_id"]),
            parameters={
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
                "observation_id": str(args.get("observation_id") or ""),
                "value": str(args.get("value") or ""),
                **self._post_observe_parameters(args),
            },
        )
        return self._attach_post_observation_image(payload)

    def browser_press(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "press",
            session_id=str(args["session_id"]),
            parameters={
                "key": str(args["key"]),
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
                "observation_id": str(args.get("observation_id") or ""),
                **self._post_observe_parameters(args),
            },
        )
        return self._attach_post_observation_image(payload)

    def browser_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "screenshot",
            session_id=str(args["session_id"]),
            parameters={"full_page": bool(args.get("full_page", False))},
            permission="browser_observe",
        )
        encoded = str(payload.get("data_base64", "") or "")
        payload = self._attach_image(payload)
        path = str(args.get("path") or "").strip()
        if not path:
            return payload
        self._assert_tool_capabilities(
            "browser_screenshot",
            frozenset({Capability.FILESYSTEM_WRITE}),
        )
        data = self._decode_image(encoded)
        target = self.workspace.writable(path)
        if target.absolute.suffix.lower() != ".png":
            raise ToolError("INVALID_PATH", "Browser screenshot 仅支持 .png 输出。", "validation")
        target.absolute.parent.mkdir(parents=True, exist_ok=True)
        target.absolute.write_bytes(data)
        payload.update({"path": target.display, "bytes": len(data)})
        return payload

    @staticmethod
    def _decode_image(encoded: str) -> bytes:
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("HOST_CAPABILITY_ERROR", "Browser screenshot 数据无效。", "runtime") from exc

    def _attach_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = str(payload.pop("data_base64", "") or "")
        data = self._decode_image(encoded)
        if len(data) > 25 * 1024 * 1024:
            raise ToolError("OUTPUT_TOO_LARGE", "Browser screenshot 超过 25 MiB 限制。", "runtime")
        normalized = {
            **payload,
            "mime_type": "image/png",
            "bytes": len(data),
            "_image": ("image/png", encoded),
        }
        return normalized

    def browser_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "status",
            session_id=str(args["session_id"]),
            permission=None,
        )

    def browser_close(self, args: dict[str, Any]) -> dict[str, Any]:
        # Closing an already-created Host session is always allowed so users are
        # never forced to grant a new permission just to clean up resources.
        return self._browser_call(
            "close",
            session_id=str(args["session_id"]),
            permission=None,
        )
