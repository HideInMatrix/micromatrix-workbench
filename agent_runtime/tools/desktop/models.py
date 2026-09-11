from __future__ import annotations

from enum import StrEnum


class DesktopMode(StrEnum):
    OBSERVE = "observe"
    CONTROL = "control"


class DesktopAction(StrEnum):
    TARGETS = "targets"
    ATTACH = "attach"
    OBSERVE = "observe"
    CLICK = "click"
    TYPE = "type"
    KEYPRESS = "keypress"
    SCROLL = "scroll"
    DRAG = "drag"
    DETACH = "detach"


__all__ = ["DesktopAction", "DesktopMode"]
