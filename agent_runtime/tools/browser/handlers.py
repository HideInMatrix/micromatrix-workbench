from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from ...errors import ToolError


class BrowserHandlers:
    def browser_manage(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "")
        handlers = {
            "open": self.browser_open,
            "navigate": self.browser_navigate,
            "snapshot": self.browser_snapshot,
            "click": self.browser_click,
            "fill": self.browser_fill,
            "press": self.browser_press,
            "screenshot": self.browser_screenshot,
            "status": self.browser_status,
            "close": self.browser_close,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ToolError("INVALID_ARGUMENT", f"不支持 Browser action: {action}", "validation")
        return handler(args)

    def _browser_control_required(self) -> None:
        if self._permission_granted("browser_control"):
            return
        raise ToolError(
            "PERMISSION_REQUIRED",
            "需要启动或控制 Workbench Desktop Host 托管的隔离浏览器会话。",
            "permission",
            False,
            {
                "permission": "browser_control",
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
        require_control: bool = True,
    ) -> dict[str, Any]:
        if require_control:
            self._browser_control_required()
        broker = self.local_permission_broker
        invoke = getattr(broker, "invoke_host_capability", None) if broker is not None else None
        if not callable(invoke):
            raise ToolError(
                "HOST_CAPABILITY_UNAVAILABLE",
                "当前 Runtime 未连接 Workbench Desktop Host Capability 通道。",
                "runtime",
                True,
                {"capability": "browser"},
            )
        response = invoke(
            "browser",
            action,
            parameters=dict(parameters or {}),
            session_id=session_id,
        )
        if not getattr(response, "ok", False) or not isinstance(getattr(response, "result", None), dict):
            status = str(getattr(response, "status", "error") or "error")
            raise ToolError(
                "HOST_CAPABILITY_ERROR",
                str(getattr(response, "error", "") or "Browser Host Capability 操作失败。"),
                "runtime",
                status in {"timeout", "unavailable"},
                {"capability": "browser", "action": action, "status": status},
            )
        return dict(response.result)

    def browser_open(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call("open", parameters={
            "url": str(args.get("url") or "about:blank"),
            "headless": bool(args.get("headless", True)),
            "width": int(args.get("width", 1440)),
            "height": int(args.get("height", 900)),
        })

    def browser_navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "navigate",
            session_id=str(args["session_id"]),
            parameters={"url": str(args["url"])},
        )

    def browser_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "snapshot",
            session_id=str(args["session_id"]),
            parameters={
                "max_text": int(args.get("max_text", 12_000)),
                "max_elements": int(args.get("max_elements", 300)),
            },
        )

    def browser_click(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "click",
            session_id=str(args["session_id"]),
            parameters={
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
            },
        )

    def browser_fill(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "fill",
            session_id=str(args["session_id"]),
            parameters={
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
                "value": str(args.get("value") or ""),
            },
        )

    def browser_press(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call(
            "press",
            session_id=str(args["session_id"]),
            parameters={
                "key": str(args["key"]),
                "ref": str(args.get("ref") or ""),
                "selector": str(args.get("selector") or ""),
            },
        )

    def browser_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._browser_call(
            "screenshot",
            session_id=str(args["session_id"]),
            parameters={"full_page": bool(args.get("full_page", False))},
        )
        encoded = str(payload.pop("data_base64", "") or "")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("HOST_CAPABILITY_ERROR", "Browser screenshot 数据无效。", "runtime") from exc
        if len(data) > 25 * 1024 * 1024:
            raise ToolError("OUTPUT_TOO_LARGE", "Browser screenshot 超过 25 MiB 限制。", "runtime")
        target = self.workspace.writable(str(args.get("path") or "browser-screenshot.png"))
        if target.absolute.suffix.lower() != ".png":
            raise ToolError("INVALID_PATH", "Browser screenshot 仅支持 .png 输出。", "validation")
        target.absolute.parent.mkdir(parents=True, exist_ok=True)
        target.absolute.write_bytes(data)
        return {
            **payload,
            "path": target.display,
            "bytes": len(data),
            "mime_type": "image/png",
        }

    def browser_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._browser_call("status", session_id=str(args["session_id"]))

    def browser_close(self, args: dict[str, Any]) -> dict[str, Any]:
        # Closing an already-created Host session is always allowed so users are
        # never forced to grant a new permission just to clean up resources.
        return self._browser_call(
            "close",
            session_id=str(args["session_id"]),
            require_control=False,
        )
