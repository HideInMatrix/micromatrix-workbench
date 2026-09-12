from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .drivers.base import DesktopTarget, WindowBounds


@dataclass(slots=True)
class DesktopObservationState:
    bounds: WindowBounds
    image_width: int
    image_height: int
    observed_at_monotonic: float
    elements: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class DesktopSession:
    session_id: str
    server_id: str
    principal_hash: str
    generation: str
    target_id: str
    target: DesktopTarget
    mode: str
    last_observation_id: str = ""
    last_bounds: WindowBounds | None = None
    last_image_width: int = 0
    last_image_height: int = 0
    last_elements: dict[str, dict[str, Any]] = field(default_factory=dict)
    observations: dict[str, DesktopObservationState] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)


__all__ = ["DesktopObservationState", "DesktopSession"]
