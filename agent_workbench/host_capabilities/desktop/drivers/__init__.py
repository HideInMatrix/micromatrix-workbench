from __future__ import annotations

import sys

from .base import DesktopDriver, UnsupportedDesktopDriver


def build_desktop_driver() -> DesktopDriver:
    if sys.platform == "darwin":
        from .macos import MacOSDesktopDriver

        return MacOSDesktopDriver()
    if sys.platform == "win32":
        from .windows import WindowsDesktopDriver

        return WindowsDesktopDriver()
    return UnsupportedDesktopDriver(platform=sys.platform)


__all__ = ["DesktopDriver", "UnsupportedDesktopDriver", "build_desktop_driver"]
