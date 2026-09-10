from __future__ import annotations

from agent_workbench.host_execution import (
    HostApplication,
    HostApplicationResolutionError,
    resolve_url_scheme_applications,
)

from .base import HostCapabilityError


_CHROMIUM_MARKERS = ("chrome", "chromium", "edge", "brave", "vivaldi", "opera")


BrowserApplication = HostApplication


def _is_chromium(application: HostApplication) -> bool:
    identity = f"{application.identity} {application.executable.name}".lower()
    return any(marker in identity for marker in _CHROMIUM_MARKERS)


def resolve_chromium_browser() -> HostApplication:
    """Select an OS-registered application compatible with the CDP provider."""

    try:
        candidates = resolve_url_scheme_applications("https")
    except HostApplicationResolutionError as exc:
        raise HostCapabilityError(str(exc)) from exc
    usable = [item for item in candidates if _is_chromium(item)]
    if not usable:
        raise HostCapabilityError(
            "当前用户没有注册可用的 Chromium/CDP 浏览器；不会通过固定安装路径猜测浏览器位置。"
        )
    return next((item for item in usable if item.is_default), usable[0])


__all__ = ["BrowserApplication", "resolve_chromium_browser"]
