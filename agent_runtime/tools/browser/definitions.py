from __future__ import annotations

from ...core.tool import ToolAnnotations, ToolDefinition, ToolExecutionKind
from ...permissions.capabilities import Capability, OperationPermission
from ...schemas import B, I, S, obj


_HOST = ToolExecutionKind.HOST_CAPABILITY
_CAP = frozenset({Capability.HOST_CAPABILITY_USE})
_CONTROL = frozenset({OperationPermission.BROWSER_CONTROL})
_OBSERVE = frozenset({OperationPermission.BROWSER_OBSERVE})
_POST_OBSERVE = {
    "observe_after": {**B, "default": True},
    "max_text": {**I, "minimum": 500, "maximum": 50_000, "default": 12_000},
    "max_elements": {**I, "minimum": 1, "maximum": 1000, "default": 300},
}
_TARGET = {
    "ref": S,
    "selector": S,
    "observation_id": S,
}


BROWSER_TOOLS = (
    ToolDefinition(
        "browser_open", "Open browser",
        "Create an isolated Desktop Host browser session. The user's normal browser profile is never reused.",
        obj({"url": {**S, "default": "about:blank"}, "headless": {**B, "default": True}, "width": {**I, "minimum": 320, "maximum": 3840, "default": 1440}, "height": {**I, "minimum": 240, "maximum": 2160, "default": 900}, **_POST_OBSERVE}),
        "browser_open", _CAP, ToolAnnotations(destructive=True, open_world=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_CONTROL,
    ),
    ToolDefinition(
        "browser_navigate", "Navigate browser", "Navigate a Host-managed browser session to an http/https URL.",
        obj({"session_id": {**S, "minLength": 8}, "url": {**S, "minLength": 1}, **_POST_OBSERVE}, ("session_id", "url")),
        "browser_navigate", _CAP, ToolAnnotations(destructive=True, open_world=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_CONTROL,
    ),
    ToolDefinition(
        "browser_snapshot", "Browser snapshot", "Return bounded page text plus interactive elements with stable refs for the current page state.",
        obj({"session_id": {**S, "minLength": 8}, "max_text": {**I, "minimum": 500, "maximum": 50_000, "default": 12_000}, "max_elements": {**I, "minimum": 1, "maximum": 1000, "default": 300}}, ("session_id",)),
        "browser_snapshot", _CAP, ToolAnnotations(read_only=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_OBSERVE,
    ),
    ToolDefinition(
        "browser_click", "Browser click", "Click an element by current snapshot ref+observation_id or CSS selector, then optionally observe the resulting page.",
        obj({"session_id": {**S, "minLength": 8}, **_TARGET, **_POST_OBSERVE}, ("session_id",)),
        "browser_click", _CAP, ToolAnnotations(destructive=True, open_world=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_CONTROL,
    ),
    ToolDefinition(
        "browser_fill", "Browser fill", "Fill an input/contenteditable element by current snapshot ref+observation_id or CSS selector, then optionally observe.",
        obj({"session_id": {**S, "minLength": 8}, **_TARGET, "value": S, **_POST_OBSERVE}, ("session_id", "value")),
        "browser_fill", _CAP, ToolAnnotations(destructive=True, open_world=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_CONTROL,
    ),
    ToolDefinition(
        "browser_press", "Browser key press", "Send a keyboard key to the current page, optionally focusing a referenced element first.",
        obj({"session_id": {**S, "minLength": 8}, "key": {**S, "minLength": 1}, **_TARGET, **_POST_OBSERVE}, ("session_id", "key")),
        "browser_press", _CAP, ToolAnnotations(destructive=True, open_world=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_CONTROL,
    ),
    ToolDefinition(
        "browser_screenshot", "Browser screenshot", "Capture a PNG from the Host-managed browser. The image is returned directly; path is optional and explicitly saves a copy inside the workspace.",
        obj({"session_id": {**S, "minLength": 8}, "path": S, "full_page": {**B, "default": False}}, ("session_id",)),
        "browser_screenshot", _CAP, ToolAnnotations(read_only=True), execution_kind=_HOST,
        preflight_handler_name="browser_preflight", operation_permissions=_OBSERVE,
    ),
    ToolDefinition(
        "browser_status", "Browser status", "Return Host-managed browser session health and provider metadata.",
        obj({"session_id": {**S, "minLength": 8}}, ("session_id",)),
        "browser_status", _CAP, ToolAnnotations(read_only=True, idempotent=True), execution_kind=_HOST,
    ),
    ToolDefinition(
        "browser_close", "Close browser", "Close a Host-managed browser session and delete its isolated temporary profile.",
        obj({"session_id": {**S, "minLength": 8}}, ("session_id",)),
        "browser_close", _CAP, ToolAnnotations(destructive=True, idempotent=True), execution_kind=_HOST,
    ),
)
