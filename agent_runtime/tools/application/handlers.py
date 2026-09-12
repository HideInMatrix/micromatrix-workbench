from __future__ import annotations

import hashlib
from typing import Any

from ...errors import ToolError
from ...protocol import current_request_context


class ApplicationHandlers:
    _MUTATING_ACTIONS = frozenset({"launch", "activate", "quit"})

    def _application_call(self, action: str, *, parameters: dict[str, Any]) -> dict[str, Any]:
        broker = self.local_permission_broker
        invoke = getattr(broker, "invoke_host_capability", None) if broker is not None else None
        if not callable(invoke):
            raise ToolError(
                "HOST_DISCONNECTED",
                "当前 Runtime 未连接 Workbench Desktop Host Capability 通道。",
                "runtime",
                True,
                {"capability": "application", "action": action, "stage": "preflight", "cause_code": "HOST_NOT_CONFIGURED"},
            )
        context = current_request_context()
        principal = context.principal if context and context.principal else "anonymous"
        host_parameters = dict(parameters)
        host_parameters["_principal_hash"] = hashlib.sha256(
            principal.encode("utf-8", "surrogateescape")
        ).hexdigest()
        response = invoke("application", action, parameters=host_parameters)
        if not getattr(response, "ok", False) or not isinstance(getattr(response, "result", None), dict):
            status = str(getattr(response, "status", "error") or "error")
            details = dict(getattr(response, "details", None) or {})
            cause_code = str(details.get("cause_code") or "APPLICATION_CAPABILITY_FAILED")
            if action in self._MUTATING_ACTIONS:
                if details.get("host_ack_at_ms") is None:
                    details["action_state"] = "not_started"
                elif status in {"timeout", "ack_timeout", "unavailable"}:
                    details["action_state"] = "unknown"
                else:
                    details["action_state"] = "failed"
            details.update({"capability": "application", "action": action, "status": status})
            raise ToolError(
                cause_code,
                str(getattr(response, "error", "") or "Application Host Capability 操作失败。"),
                "runtime",
                status in {"timeout", "ack_timeout", "unavailable"},
                details,
            )
        return dict(response.result)

    def application_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "")
        if action not in self._MUTATING_ACTIONS:
            return {}
        parameters = {key: value for key, value in args.items() if key != "action"}
        parameters["_preflight"] = True
        return self._application_call(action, parameters=parameters)

    def application(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "")
        parameters = {key: value for key, value in args.items() if key != "action"}
        return self._application_call(action, parameters=parameters)


__all__ = ["ApplicationHandlers"]
