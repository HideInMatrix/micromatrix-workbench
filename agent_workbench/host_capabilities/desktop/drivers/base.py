from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...base import HostCapabilityError


@dataclass(frozen=True, slots=True)
class WindowBounds:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class DesktopTarget:
    window_id: int
    owner_pid: int
    application_name: str
    window_title: str
    bounds: WindowBounds
    onscreen: bool
    application_id: str = ""
    application_identity_fingerprint: str = ""
    persistent_authorization_supported: bool = False
    owner_window_id: int = 0
    relationship: str = "top_level"
    control_protected_reason: str = ""

    @property
    def identity(self) -> tuple[int, int, str]:
        return (
            self.window_id,
            self.owner_pid,
            self.application_id or self.application_name,
        )


class DesktopDriver(Protocol):
    name: str
    platform: str

    def support_status(self) -> dict[str, Any]: ...

    def list_targets(self, *, max_results: int) -> list[DesktopTarget]: ...

    def find_target(self, target: DesktopTarget) -> DesktopTarget | None: ...

    def check_observe_permission(self) -> bool | None: ...

    def check_control_permission(self) -> bool | None: ...

    def check_target_control_permission(self, target: DesktopTarget) -> bool | None: ...

    def capture(self, target: DesktopTarget) -> dict[str, Any]: ...

    def is_focused(self, target: DesktopTarget) -> bool | None: ...

    def click(
        self,
        target: DesktopTarget,
        *,
        x: float,
        y: float,
        button: str,
        click_count: int,
    ) -> None: ...

    def type_text(self, target: DesktopTarget, text: str) -> None: ...

    def keypress(self, target: DesktopTarget, key: str) -> None: ...

    def scroll(
        self,
        target: DesktopTarget,
        *,
        delta_x: int,
        delta_y: int,
        x: float | None,
        y: float | None,
    ) -> None: ...

    def drag(
        self,
        target: DesktopTarget,
        *,
        path: list[tuple[float, float]],
        button: str,
        duration_ms: int,
    ) -> None: ...

    def accessibility_elements(
        self,
        target: DesktopTarget,
        *,
        max_elements: int,
    ) -> dict[str, Any]: ...


class UnsupportedDesktopDriver:
    name = "unsupported"

    def __init__(self, *, platform: str) -> None:
        self.platform = platform

    def support_status(self) -> dict[str, Any]:
        return {
            "supported": False,
            "platform": self.platform,
            "driver": self.name,
            "reason": "desktop_driver_unavailable",
        }

    def _unsupported(self) -> None:
        raise HostCapabilityError(
            f"当前平台 {self.platform} 尚未提供 Desktop Computer Use 驱动。",
            code="DESKTOP_PLATFORM_UNSUPPORTED",
            stage="preflight",
        )

    def list_targets(self, *, max_results: int) -> list[DesktopTarget]:
        self._unsupported()
        return []

    def find_target(self, target: DesktopTarget) -> DesktopTarget | None:
        self._unsupported()
        return None

    def check_observe_permission(self) -> bool | None:
        return None

    def check_control_permission(self) -> bool | None:
        return None

    def check_target_control_permission(self, target: DesktopTarget) -> bool | None:
        return None

    def capture(self, target: DesktopTarget) -> dict[str, Any]:
        self._unsupported()
        return {}

    def is_focused(self, target: DesktopTarget) -> bool | None:
        self._unsupported()
        return None

    def click(self, target: DesktopTarget, **kwargs: Any) -> None:
        self._unsupported()

    def type_text(self, target: DesktopTarget, text: str) -> None:
        self._unsupported()

    def keypress(self, target: DesktopTarget, key: str) -> None:
        self._unsupported()

    def scroll(self, target: DesktopTarget, **kwargs: Any) -> None:
        self._unsupported()

    def drag(self, target: DesktopTarget, **kwargs: Any) -> None:
        self._unsupported()

    def accessibility_elements(self, target: DesktopTarget, *, max_elements: int) -> dict[str, Any]:
        return {
            "supported": False,
            "reason": "desktop_driver_unavailable",
            "elements": [],
        }


__all__ = ["DesktopDriver", "DesktopTarget", "UnsupportedDesktopDriver", "WindowBounds"]
