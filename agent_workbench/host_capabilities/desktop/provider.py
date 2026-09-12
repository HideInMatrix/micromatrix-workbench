from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from ..base import HostCapabilityDescriptor, HostCapabilityError
from .drivers import build_desktop_driver
from .drivers.base import DesktopControlDecision, DesktopDriver, DesktopTarget, WindowBounds
from .sessions import DesktopObservationState, DesktopSession


_OBSERVATION_HISTORY_LIMIT = 8
_OBSERVATION_MAX_AGE_SECONDS = 120.0


class DesktopHostCapability:
    descriptor = HostCapabilityDescriptor(
        name="desktop",
        provider="native_desktop",
        session_based=True,
        operations=(
            "targets",
            "attach",
            "observe",
            "click",
            "type",
            "keypress",
            "scroll",
            "drag",
            "detach",
        ),
    )

    def __init__(self, *, generation: str = "", driver: DesktopDriver | None = None) -> None:
        self._generation = generation or "standalone"
        self._generation_prefix = self._generation[:10]
        self._driver = driver or build_desktop_driver()
        self._sessions: dict[str, DesktopSession] = {}
        self._targets: dict[str, tuple[str, str, DesktopTarget, float]] = {}
        self._target_ids: dict[tuple[str, str, tuple[int, int, str]], str] = {}
        self._lock = threading.RLock()
        self._input_lock = threading.RLock()
        self._input_epochs: dict[str, int] = {}

    def _input_epoch(self, server_id: str) -> int:
        with self._lock:
            return int(self._input_epochs.get(server_id, 0))

    def _assert_input_epoch(self, server_id: str, expected: int) -> None:
        if self._input_epoch(server_id) != expected:
            raise HostCapabilityError(
                "本地用户已停止该 Profile 的 Desktop 输入；请重新发起并重新观察。",
                code="DESKTOP_INPUT_STOPPED",
                stage="input",
            )

    def stop_server_input(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._input_epochs[server_id] = int(self._input_epochs.get(server_id, 0)) + 1
            session_count = sum(
                1 for session in self._sessions.values() if session.server_id == server_id
            )
            epoch = self._input_epochs[server_id]
        return {
            "server_id": server_id,
            "stopped": True,
            "input_epoch": epoch,
            "affected_sessions": session_count,
        }

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        principal_hash = str(parameters.pop("_principal_hash", "") or "").strip()
        if not principal_hash:
            raise HostCapabilityError(
                "Desktop Host 请求缺少已认证 principal 绑定。",
                code="DESKTOP_PRINCIPAL_REQUIRED",
                stage="authorization",
            )
        if bool(parameters.pop("_preflight", False)):
            return self._preflight(
                action,
                server_id=server_id,
                principal_hash=principal_hash,
                session_id=session_id,
                parameters=parameters,
            )
        if action == "targets":
            return self._list_targets(server_id, principal_hash, parameters)
        if action == "attach":
            return self._attach(server_id, principal_hash, parameters)
        if action == "detach":
            return self._detach(server_id, principal_hash, session_id)

        session = self._session(server_id, principal_hash, session_id)
        with session.lock:
            if action == "observe":
                return self._observe(session, parameters)
            if action == "click":
                result = self._click(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "type":
                result = self._type(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "keypress":
                result = self._keypress(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "scroll":
                result = self._scroll(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "drag":
                result = self._drag(session, parameters)
                return self._with_post_observation(session, result, parameters)
        raise HostCapabilityError(
            f"不支持 Desktop action: {action}",
            code="DESKTOP_ACTION_UNSUPPORTED",
            stage="validation",
        )

    def _cleanup_target_tokens(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                token
                for token, (_, _, _, deadline) in self._targets.items()
                if deadline <= now
            ]
            for token in expired:
                server_id, principal_hash, target, _ = self._targets.pop(token)
                key = (server_id, principal_hash, target.identity)
                if self._target_ids.get(key) == token:
                    self._target_ids.pop(key, None)

    def _token_for_target(
        self,
        server_id: str,
        principal_hash: str,
        target: DesktopTarget,
    ) -> str:
        self._cleanup_target_tokens()
        key = (server_id, principal_hash, target.identity)
        with self._lock:
            existing = self._target_ids.get(key)
            if existing:
                self._targets[existing] = (
                    server_id,
                    principal_hash,
                    target,
                    time.monotonic() + 120.0,
                )
                return existing
            token = f"dt_{self._generation_prefix}_{secrets.token_urlsafe(12)}"
            self._targets[token] = (
                server_id,
                principal_hash,
                target,
                time.monotonic() + 120.0,
            )
            self._target_ids[key] = token
            return token

    def _list_targets(
        self,
        server_id: str,
        principal_hash: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        max_results = max(1, min(int(parameters.get("max_results", 30)), 100))
        targets = self._driver.list_targets(max_results=max_results)
        target_tokens = {
            target.window_id: self._token_for_target(server_id, principal_hash, target)
            for target in targets
        }
        return {
            "provider": self.descriptor.provider,
            "generation": self._generation,
            "support": self._driver.support_status(),
            "targets": [
                {
                    "target_id": target_tokens[target.window_id],
                    "application": {
                        "name": target.application_name,
                        "id": target.application_id or None,
                    },
                    "window": {
                        "width": int(round(target.bounds.width)),
                        "height": int(round(target.bounds.height)),
                        "onscreen": target.onscreen,
                        "visibility": "unknown",
                        "title_exposed": False,
                        "relationship": target.relationship,
                        "related_target_id": target_tokens.get(target.owner_window_id),
                        "control_eligible": self._control_decision(target).allowed is not False,
                    },
                }
                for target in targets
            ],
            "truncated": len(targets) >= max_results,
        }

    def _system_permissions(self) -> dict[str, str]:
        return {
            "observe": self._permission_status(self._driver.check_observe_permission()),
            "control": self._permission_status(self._driver.check_control_permission()),
        }

    def _control_decision(self, target: DesktopTarget) -> DesktopControlDecision:
        return self._driver.control_decision(target)

    def _ensure_target_control_allowed(self, target: DesktopTarget) -> None:
        decision = self._control_decision(target)
        if decision.allowed is False:
            raise HostCapabilityError(
                decision.message or "当前 Desktop Host 无法安全控制该目标窗口。",
                code=decision.code or "DESKTOP_TARGET_CONTROL_BLOCKED",
                stage=decision.stage,
            )

    def _preflight(
        self,
        action: str,
        *,
        server_id: str,
        principal_hash: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "attach":
            target_id = str(parameters.get("target_id") or "").strip()
            mode = str(parameters.get("mode") or "").strip()
            if mode not in {"observe", "control"}:
                raise HostCapabilityError(
                    "Desktop attach mode 必须为 observe 或 control。",
                    code="INVALID_DESKTOP_MODE",
                    stage="validation",
                )
            target = self._resolve_target_token(
                server_id,
                principal_hash,
                target_id,
            )
            if mode == "observe" and self._driver.check_observe_permission() is False:
                raise HostCapabilityError(
                    "系统尚未授予 Workbench 桌面观察所需的屏幕访问权限。",
                    code="DESKTOP_SCREEN_PERMISSION_REQUIRED",
                    stage="system_permission",
                )
            if mode == "control":
                self._ensure_target_control_allowed(target)
            return {
                "preflight": True,
                "mode": mode,
                "target": self._authorized_target_metadata(target_id, target),
                "system_permissions": self._system_permissions(),
            }
        if action in {"targets", "detach"}:
            return {
                "preflight": True,
                "system_permissions": self._system_permissions(),
            }

        session = self._session(server_id, principal_hash, session_id)
        with session.lock:
            if action == "observe":
                target = self._refresh_session_target(session)
                if self._driver.check_observe_permission() is False:
                    raise HostCapabilityError(
                        "系统尚未授予 Workbench 桌面观察所需的屏幕访问权限。",
                        code="DESKTOP_SCREEN_PERMISSION_REQUIRED",
                        stage="system_permission",
                    )
            elif action in {"click", "type", "keypress", "scroll", "drag"}:
                target = self._validate_control_observation(
                    session,
                    parameters,
                    consume=False,
                )
                self._ensure_target_control_allowed(target)
                if (
                    bool(parameters.get("observe_after", True))
                    and self._driver.check_observe_permission() is False
                ):
                    raise HostCapabilityError(
                        "动作后观察需要当前平台的桌面捕获权限/能力。",
                        code="DESKTOP_SCREEN_PERMISSION_REQUIRED",
                        stage="system_permission",
                    )
            else:
                raise HostCapabilityError(
                    f"不支持 Desktop action: {action}",
                    code="DESKTOP_ACTION_UNSUPPORTED",
                    stage="validation",
                )
            return {
                "preflight": True,
                "mode": session.mode,
                "target": self._authorized_target_metadata(session.target_id, target),
                "system_permissions": self._system_permissions(),
            }

    def _resolve_target_token(
        self,
        server_id: str,
        principal_hash: str,
        target_id: str,
    ) -> DesktopTarget:
        self._cleanup_target_tokens()
        with self._lock:
            record = self._targets.get(target_id)
        if record is None:
            raise HostCapabilityError(
                "Desktop target_id 已过期或不是由当前 Host generation 枚举得到。",
                code="DESKTOP_TARGET_TOKEN_EXPIRED",
                stage="target",
            )
        owner_server_id, owner_principal_hash, target, _ = record
        if owner_server_id != server_id or owner_principal_hash != principal_hash:
            raise HostCapabilityError(
                "Desktop target_id 不属于当前客户端/Profile。",
                code="DESKTOP_TARGET_TOKEN_EXPIRED",
                stage="target",
            )
        current = self._driver.find_target(target)
        if current is None:
            raise HostCapabilityError(
                "Desktop 目标窗口已关闭或身份发生变化。",
                code="DESKTOP_TARGET_GONE",
                stage="target",
            )
        return current

    def _attach(
        self,
        server_id: str,
        principal_hash: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        target_id = str(parameters.get("target_id") or "").strip()
        mode = str(parameters.get("mode") or "").strip()
        if mode not in {"observe", "control"}:
            raise HostCapabilityError(
                "Desktop attach mode 必须为 observe 或 control。",
                code="INVALID_DESKTOP_MODE",
                stage="validation",
            )
        target = self._resolve_target_token(server_id, principal_hash, target_id)
        if mode == "observe" and self._driver.check_observe_permission() is False:
            raise HostCapabilityError(
                "系统尚未授予 Workbench 桌面观察所需的屏幕访问权限。",
                code="DESKTOP_SCREEN_PERMISSION_REQUIRED",
                stage="system_permission",
            )
        if mode == "control":
            self._ensure_target_control_allowed(target)
        session_id = f"ds_{self._generation_prefix}_{secrets.token_urlsafe(18)}"
        session = DesktopSession(
            session_id=session_id,
            server_id=server_id,
            principal_hash=principal_hash,
            generation=self._generation,
            target_id=target_id,
            target=target,
            mode=mode,
        )
        with self._lock:
            self._sessions[session_id] = session
        return {
            "session_id": session_id,
            "host_generation": self._generation,
            "provider": self.descriptor.provider,
            "mode": mode,
            "target": self._authorized_target_metadata(target_id, target),
            "system_permissions": self._system_permissions(),
        }

    @staticmethod
    def _permission_status(value: bool | None) -> str:
        return "granted" if value is True else "denied" if value is False else "unknown"

    @staticmethod
    def _bounds_equal(left: WindowBounds, right: WindowBounds) -> bool:
        return all(
            abs(a - b) <= 0.5
            for a, b in (
                (left.x, right.x),
                (left.y, right.y),
                (left.width, right.width),
                (left.height, right.height),
            )
        )

    def _authorized_target_metadata(self, target_id: str, target: DesktopTarget) -> dict[str, Any]:
        return {
            "target_id": target_id,
            "application": {
                "name": target.application_name,
                "pid": target.owner_pid,
                "id": target.application_id or None,
                "identity_fingerprint": target.application_identity_fingerprint or None,
            },
            "window": {
                "title": target.window_title,
                "bounds": target.bounds.to_dict(),
                "onscreen": target.onscreen,
                "minimized": "unknown",
                "visibility": "unknown",
                "occlusion": "unknown",
                "relationship": target.relationship,
                "control_eligible": self._control_decision(target).allowed is not False,
            },
        }

    def _session(
        self,
        server_id: str,
        principal_hash: str,
        session_id: str,
    ) -> DesktopSession:
        if not session_id:
            raise HostCapabilityError(
                "缺少 desktop session_id。",
                code="SESSION_NOT_FOUND",
                stage="session",
            )
        with self._lock:
            session = self._sessions.get(session_id)
        if (
            session is None
            or session.server_id != server_id
            or session.principal_hash != principal_hash
        ):
            if session_id.startswith("ds_") and not session_id.startswith(
                f"ds_{self._generation_prefix}_"
            ):
                raise HostCapabilityError(
                    "Desktop Session 属于已失效的 Host generation。",
                    code="SESSION_EXPIRED",
                    stage="session",
                )
            raise HostCapabilityError(
                "Desktop Session 不存在或不属于当前 MCP Server。",
                code="SESSION_NOT_FOUND",
                stage="session",
            )
        return session

    def _refresh_session_target(self, session: DesktopSession) -> DesktopTarget:
        current = self._driver.find_target(session.target)
        if current is None:
            raise HostCapabilityError(
                "Desktop 目标窗口已关闭或身份发生变化。",
                code="DESKTOP_TARGET_GONE",
                stage="target",
            )
        session.target = current
        return current

    def _observe(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._refresh_session_target(session)
        capture = self._driver.capture(target)
        image = capture.get("image") if isinstance(capture.get("image"), dict) else {}
        width = int(image.get("width") or 0)
        height = int(image.get("height") or 0)
        if width <= 0 or height <= 0:
            raise HostCapabilityError(
                "Desktop observation 没有有效图像尺寸。",
                code="DESKTOP_CAPTURE_FAILED",
                stage="capture",
            )
        max_elements = max(0, min(int(parameters.get("max_elements", 200)), 1000))
        accessibility = self._driver.accessibility_elements(
            target,
            max_elements=max_elements,
        )
        elements_raw = accessibility.get("elements") if isinstance(accessibility, dict) else []
        elements = [item for item in elements_raw if isinstance(item, dict)] if isinstance(elements_raw, list) else []
        observation_id = secrets.token_urlsafe(12)
        session.last_observation_id = observation_id
        session.last_bounds = target.bounds
        session.last_image_width = width
        session.last_image_height = height
        session.last_elements = {
            str(item.get("ref")): item
            for item in elements
            if str(item.get("ref") or "")
        }
        session.observations[observation_id] = DesktopObservationState(
            bounds=target.bounds,
            image_width=width,
            image_height=height,
            observed_at_monotonic=time.monotonic(),
            elements=dict(session.last_elements),
        )
        while len(session.observations) > _OBSERVATION_HISTORY_LIMIT:
            session.observations.pop(next(iter(session.observations)))
        return {
            "session_id": session.session_id,
            "host_generation": session.generation,
            "observation_id": observation_id,
            "observed_at_ms": int(time.time() * 1000),
            "target": self._authorized_target_metadata(session.target_id, target),
            "display_id": None,
            "display_id_status": "unavailable",
            "accessibility": {
                **(accessibility if isinstance(accessibility, dict) else {}),
                "elements": elements,
            },
            **capture,
        }

    def _validate_control_observation(
        self,
        session: DesktopSession,
        parameters: dict[str, Any],
        *,
        consume: bool,
    ) -> DesktopTarget:
        if session.mode != "control":
            raise HostCapabilityError(
                "当前 Desktop Session 仅允许 observe，不能执行输入动作。",
                code="DESKTOP_READ_ONLY_SESSION",
                stage="authorization",
            )
        observation_id = str(parameters.get("observation_id") or "")
        observation = session.observations.get(observation_id)
        if (
            observation is None
            or time.monotonic() - observation.observed_at_monotonic
            > _OBSERVATION_MAX_AGE_SECONDS
        ):
            session.observations.pop(observation_id, None)
            raise HostCapabilityError(
                "Desktop observation_id 已过期；请重新 observe 后再执行输入动作。",
                code="STALE_DESKTOP_OBSERVATION",
                stage="validation",
            )
        # Keep each accepted observation bound to the exact coordinate mapping
        # and accessibility refs that were captured with that frame.  A newer
        # observation may be produced by another preflight/UI consumer without
        # invalidating an otherwise-safe recent frame from the same Session.
        session.last_observation_id = observation_id
        session.last_bounds = observation.bounds
        session.last_image_width = observation.image_width
        session.last_image_height = observation.image_height
        session.last_elements = dict(observation.elements)
        current = self._refresh_session_target(session)
        # Re-evaluate target-specific protection immediately before every
        # input action. Preflight/approval may have happened earlier and a
        # platform security boundary (for example Windows input desktop/UIPI)
        # can change before the queued action reaches the provider.
        self._ensure_target_control_allowed(current)
        if session.last_bounds is None or not self._bounds_equal(session.last_bounds, current.bounds):
            raise HostCapabilityError(
                "目标窗口位置或尺寸已变化；请重新 observe 获取新的坐标映射。",
                code="STALE_DESKTOP_OBSERVATION",
                stage="geometry",
            )
        focused = self._driver.is_focused(current)
        if focused is not True:
            raise HostCapabilityError(
                "无法确认当前前台窗口仍是已授权 Desktop 目标；为避免输入落到其他应用，请先将目标窗口置于前台并重新 observe。",
                code="DESKTOP_TARGET_NOT_FOCUSED" if focused is False else "DESKTOP_FOCUS_UNVERIFIED",
                stage="focus",
            )
        if consume:
            session.observations.pop(observation_id, None)
        return current

    def _image_to_global(self, session: DesktopSession, x: int, y: int) -> tuple[float, float]:
        bounds = session.last_bounds
        width = session.last_image_width
        height = session.last_image_height
        if bounds is None or width <= 0 or height <= 0:
            raise HostCapabilityError(
                "Desktop Session 缺少有效观察坐标映射。",
                code="STALE_DESKTOP_OBSERVATION",
                stage="geometry",
            )
        if x < 0 or y < 0 or x >= width or y >= height:
            raise HostCapabilityError(
                "Desktop 输入坐标超出本次 observation 图像范围。",
                code="INVALID_DESKTOP_COORDINATE",
                stage="validation",
            )
        return (
            bounds.x + (float(x) * bounds.width / width),
            bounds.y + (float(y) * bounds.height / height),
        )

    def _element_center(self, session: DesktopSession, element_ref: str) -> tuple[int, int]:
        element = session.last_elements.get(element_ref)
        rect = element.get("rect") if isinstance(element, dict) else None
        if not isinstance(rect, dict):
            raise HostCapabilityError(
                "当前 observation 中不存在该 Desktop element_ref。",
                code="DESKTOP_ELEMENT_NOT_FOUND",
                stage="validation",
            )
        try:
            x = float(rect["x"]) + float(rect["width"]) / 2
            y = float(rect["y"]) + float(rect["height"]) / 2
        except (KeyError, TypeError, ValueError) as exc:
            raise HostCapabilityError(
                "Desktop element_ref 缺少有效 rect。",
                code="DESKTOP_ELEMENT_NOT_FOUND",
                stage="validation",
            ) from exc
        return int(round(x)), int(round(y))

    def _click(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._validate_control_observation(session, parameters, consume=True)
        input_epoch = self._input_epoch(session.server_id)
        element_ref = str(parameters.get("element_ref") or "").strip()
        if element_ref:
            image_x, image_y = self._element_center(session, element_ref)
        else:
            image_x = int(parameters.get("x", -1))
            image_y = int(parameters.get("y", -1))
        global_x, global_y = self._image_to_global(session, image_x, image_y)
        button = str(parameters.get("button") or "left")
        click_count = max(1, min(int(parameters.get("click_count", 1)), 3))
        with self._input_lock:
            self._assert_input_epoch(session.server_id, input_epoch)
            self._driver.click(
                target,
                x=global_x,
                y=global_y,
                button=button,
                click_count=click_count,
            )
        return {
            "session_id": session.session_id,
            "clicked": True,
            "image_point": {"x": image_x, "y": image_y},
            "button": button,
            "click_count": click_count,
        }

    def _type(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._validate_control_observation(session, parameters, consume=True)
        input_epoch = self._input_epoch(session.server_id)
        text = str(parameters.get("text") or "")
        with self._input_lock:
            self._assert_input_epoch(session.server_id, input_epoch)
            self._driver.type_text(target, text)
        return {
            "session_id": session.session_id,
            "typed": True,
            "characters": len(text),
        }

    def _keypress(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._validate_control_observation(session, parameters, consume=True)
        input_epoch = self._input_epoch(session.server_id)
        key = str(parameters.get("key") or "")
        with self._input_lock:
            self._assert_input_epoch(session.server_id, input_epoch)
            self._driver.keypress(target, key)
        return {"session_id": session.session_id, "pressed": key}

    def _scroll(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._validate_control_observation(session, parameters, consume=True)
        input_epoch = self._input_epoch(session.server_id)
        x_value = parameters.get("x")
        y_value = parameters.get("y")
        if (x_value is None) != (y_value is None):
            raise HostCapabilityError(
                "scroll 的 x/y 必须同时提供或同时省略。",
                code="INVALID_DESKTOP_COORDINATE",
                stage="validation",
            )
        global_x: float | None = None
        global_y: float | None = None
        if x_value is not None and y_value is not None:
            global_x, global_y = self._image_to_global(session, int(x_value), int(y_value))
        delta_x = int(parameters.get("delta_x", 0))
        delta_y = int(parameters.get("delta_y", 0))
        if delta_x == 0 and delta_y == 0:
            raise HostCapabilityError(
                "scroll 至少需要一个非零 delta。",
                code="INVALID_DESKTOP_SCROLL",
                stage="validation",
            )
        with self._input_lock:
            self._assert_input_epoch(session.server_id, input_epoch)
            self._driver.scroll(
                target,
                delta_x=delta_x,
                delta_y=delta_y,
                x=global_x,
                y=global_y,
            )
        return {
            "session_id": session.session_id,
            "scrolled": True,
            "delta_x": delta_x,
            "delta_y": delta_y,
        }

    def _drag(self, session: DesktopSession, parameters: dict[str, Any]) -> dict[str, Any]:
        target = self._validate_control_observation(session, parameters, consume=True)
        input_epoch = self._input_epoch(session.server_id)
        raw_path = parameters.get("path")
        if not isinstance(raw_path, list) or len(raw_path) < 2:
            raise HostCapabilityError(
                "drag path 至少需要两个点。",
                code="INVALID_DESKTOP_DRAG",
                stage="validation",
            )
        path: list[tuple[float, float]] = []
        for point in raw_path:
            if not isinstance(point, dict):
                raise HostCapabilityError(
                    "drag path 包含无效点。",
                    code="INVALID_DESKTOP_DRAG",
                    stage="validation",
                )
            path.append(self._image_to_global(session, int(point["x"]), int(point["y"])))
        button = str(parameters.get("button") or "left")
        duration_ms = max(0, min(int(parameters.get("duration_ms", 300)), 10_000))
        with self._input_lock:
            self._assert_input_epoch(session.server_id, input_epoch)
            self._driver.drag(
                target,
                path=path,
                button=button,
                duration_ms=duration_ms,
            )
        return {
            "session_id": session.session_id,
            "dragged": True,
            "points": len(path),
            "duration_ms": duration_ms,
        }

    def _with_post_observation(
        self,
        session: DesktopSession,
        action_result: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        result = {**action_result, "action_state": "completed"}
        if not bool(parameters.get("observe_after", True)):
            result["observation_state"] = "skipped"
            return result
        try:
            observation = self._observe(
                session,
                {"max_elements": int(parameters.get("max_elements", 200))},
            )
        except HostCapabilityError as exc:
            result.update(
                {
                    "observation_state": "failed",
                    "observation_error": {
                        "code": exc.code,
                        "stage": exc.stage,
                        "message": str(exc),
                    },
                }
            )
            return result
        result.update(
            {
                "observation_state": "succeeded",
                "observation": observation,
            }
        )
        return result

    def _detach(
        self,
        server_id: str,
        principal_hash: str,
        session_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                if session_id.startswith("ds_") and not session_id.startswith(
                    f"ds_{self._generation_prefix}_"
                ):
                    raise HostCapabilityError(
                        "Desktop Session 属于已失效的 Host generation。",
                        code="SESSION_EXPIRED",
                        stage="session",
                    )
                return {"detached": False, "session_id": session_id}
            if (
                session.server_id != server_id
                or session.principal_hash != principal_hash
            ):
                raise HostCapabilityError(
                    "Desktop Session 不存在或不属于当前 MCP Server。",
                    code="SESSION_NOT_FOUND",
                    stage="session",
                )
            self._sessions.pop(session_id, None)
        return {
            "detached": True,
            "session_id": session_id,
            "application_closed": False,
        }

    def close_server(self, server_id: str) -> None:
        with self._lock:
            self._input_epochs[server_id] = int(self._input_epochs.get(server_id, 0)) + 1
            session_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.server_id == server_id
            ]
            for session_id in session_ids:
                self._sessions.pop(session_id, None)
            target_ids = [
                target_id
                for target_id, (owner_server_id, _, _, _) in self._targets.items()
                if owner_server_id == server_id
            ]
            for target_id in target_ids:
                owner_server_id, principal_hash, target, _ = self._targets.pop(target_id)
                self._target_ids.pop(
                    (owner_server_id, principal_hash, target.identity),
                    None,
                )

    def close(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._targets.clear()
            self._target_ids.clear()
            self._input_epochs.clear()
        close_driver = getattr(self._driver, "close", None)
        if callable(close_driver):
            close_driver()


__all__ = ["DesktopHostCapability"]
