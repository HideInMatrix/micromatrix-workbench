from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from ...base import HostCapabilityError
from .base import DesktopTarget, WindowBounds


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_INTEGRITY_LEVEL = 25
_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_SW_SHOWMINIMIZED = 2
_PW_RENDERFULLCONTENT = 0x00000002
_SRCCOPY = 0x00CC0020
_DIB_RGB_COLORS = 0
_BI_RGB = 0
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_INPUT_HARDWARE = 2
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_HWHEEL = 0x01000
_WHEEL_DELTA = 120
_MONITOR_DEFAULTTONEAREST = 2
_CCHDEVICENAME = 32
_DEFAULT_DPI = 96
_UOI_NAME = 2
_DESKTOP_READOBJECTS = 0x0001
_PROTECTED_CONTROL_EXECUTABLES = frozenset(
    {
        "consent.exe",
        "credentialuibroker.exe",
        "credprovhost.exe",
        "logonui.exe",
        "lockapp.exe",
    }
)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * _CCHDEVICENAME),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", _SID_AND_ATTRIBUTES)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", _INPUTUNION)]


def _signed_wheel(value: int) -> int:
    if value == 0:
        return 0
    magnitude = max(1, min(abs(int(value)), 1000))
    return (1 if value > 0 else -1) * magnitude * _WHEEL_DELTA


class WindowsDesktopDriver:
    name = "windows_win32"
    platform = "win32"

    def __init__(self) -> None:
        if os.name != "nt":
            raise HostCapabilityError(
                "Windows Desktop 驱动只能在 Windows Host Worker 中初始化。",
                code="DESKTOP_DRIVER_UNAVAILABLE",
                stage="driver_init",
            )
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._configure()
        self._dpi_awareness = self._enable_dpi_awareness()
        self._excluded_pids = {os.getpid(), os.getppid()}
        self._identity_cache: dict[int, tuple[str, str, bool, str]] = {}
        self._binary_fingerprint_cache: dict[tuple[str, int, int], str] = {}
        self._current_integrity_rid = self._integrity_rid_for_process(os.getpid())

    def _configure(self) -> None:
        u = self._user32
        g = self._gdi32
        k = self._kernel32
        a = self._advapi32
        u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = wintypes.LONG
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetDC.argtypes = [wintypes.HWND]
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        u.ReleaseDC.restype = ctypes.c_int
        u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        u.PrintWindow.restype = wintypes.BOOL
        u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        u.SetCursorPos.restype = wintypes.BOOL
        u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT
        u.VkKeyScanW.argtypes = [wintypes.WCHAR]
        u.VkKeyScanW.restype = ctypes.c_short
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        monitor_from_window = getattr(u, "MonitorFromWindow", None)
        if callable(monitor_from_window):
            monitor_from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
            monitor_from_window.restype = wintypes.HANDLE
        get_monitor_info = getattr(u, "GetMonitorInfoW", None)
        if callable(get_monitor_info):
            get_monitor_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFOEXW)]
            get_monitor_info.restype = wintypes.BOOL
        enum_display_monitors = getattr(u, "EnumDisplayMonitors", None)
        if callable(enum_display_monitors):
            enum_display_monitors.argtypes = [
                wintypes.HDC,
                ctypes.POINTER(wintypes.RECT),
                ctypes.c_void_p,
                wintypes.LPARAM,
            ]
            enum_display_monitors.restype = wintypes.BOOL
        get_dpi_for_window = getattr(u, "GetDpiForWindow", None)
        if callable(get_dpi_for_window):
            get_dpi_for_window.argtypes = [wintypes.HWND]
            get_dpi_for_window.restype = wintypes.UINT
        set_dpi_context = getattr(u, "SetProcessDpiAwarenessContext", None)
        if callable(set_dpi_context):
            set_dpi_context.argtypes = [ctypes.c_void_p]
            set_dpi_context.restype = wintypes.BOOL
        set_process_dpi_aware = getattr(u, "SetProcessDPIAware", None)
        if callable(set_process_dpi_aware):
            set_process_dpi_aware.argtypes = []
            set_process_dpi_aware.restype = wintypes.BOOL
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.restype = wintypes.BOOL
        u.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.GetUserObjectInformationW.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.GetCurrentProcess.argtypes = []
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        a.OpenProcessToken.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        a.GetTokenInformation.restype = wintypes.BOOL
        a.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        a.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        a.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        a.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.DeleteDC.restype = wintypes.BOOL
        g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteObject.restype = wintypes.BOOL
        g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.BitBlt.restype = wintypes.BOOL
        g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), wintypes.UINT]
        g.GetDIBits.restype = ctypes.c_int

    def _enable_dpi_awareness(self) -> str:
        set_context = getattr(self._user32, "SetProcessDpiAwarenessContext", None)
        if callable(set_context):
            try:
                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is the documented
                # pseudo handle value -4. The Host Worker is a dedicated
                # process, so process-level DPI awareness can be configured
                # before target enumeration without affecting the UI process.
                if bool(set_context(ctypes.c_void_p(-4))):
                    return "per_monitor_v2"
            except (OSError, ValueError):
                pass
        legacy = getattr(self._user32, "SetProcessDPIAware", None)
        if callable(legacy):
            try:
                if bool(legacy()):
                    return "system_aware"
            except OSError:
                pass
        return "preconfigured_or_unknown"

    def _binary_fingerprint(self, path: Path, *, size: int, mtime_ns: int) -> str:
        normalized = str(path.resolve()).lower()
        key = (normalized, int(size), int(mtime_ns))
        cached = self._binary_fingerprint_cache.get(key)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return ""
        value = digest.hexdigest()
        self._binary_fingerprint_cache[key] = value
        return value

    def _input_desktop_name(self) -> str | None:
        desktop = self._user32.OpenInputDesktop(0, False, _DESKTOP_READOBJECTS)
        if not desktop:
            return None
        try:
            needed = wintypes.DWORD()
            self._user32.GetUserObjectInformationW(
                desktop,
                _UOI_NAME,
                None,
                0,
                ctypes.byref(needed),
            )
            if needed.value <= ctypes.sizeof(wintypes.WCHAR):
                return None
            buffer = ctypes.create_unicode_buffer(max(2, needed.value // ctypes.sizeof(wintypes.WCHAR)))
            if not self._user32.GetUserObjectInformationW(
                desktop,
                _UOI_NAME,
                buffer,
                ctypes.sizeof(buffer),
                ctypes.byref(needed),
            ):
                return None
            return buffer.value.strip()
        finally:
            self._user32.CloseDesktop(desktop)

    def _integrity_rid_for_process(self, pid: int) -> int | None:
        process = (
            self._kernel32.GetCurrentProcess()
            if pid == os.getpid()
            else self._kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        )
        if not process:
            return None
        should_close_process = pid != os.getpid()
        token = wintypes.HANDLE()
        try:
            if not self._advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
                return None
            needed = wintypes.DWORD()
            self._advapi32.GetTokenInformation(
                token,
                _TOKEN_INTEGRITY_LEVEL,
                None,
                0,
                ctypes.byref(needed),
            )
            if needed.value <= 0:
                return None
            buffer = ctypes.create_string_buffer(needed.value)
            if not self._advapi32.GetTokenInformation(
                token,
                _TOKEN_INTEGRITY_LEVEL,
                buffer,
                needed.value,
                ctypes.byref(needed),
            ):
                return None
            label = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
            sid = label.Label.Sid
            if not sid:
                return None
            count_ptr = self._advapi32.GetSidSubAuthorityCount(sid)
            if not count_ptr or int(count_ptr.contents.value) <= 0:
                return None
            index = int(count_ptr.contents.value) - 1
            rid_ptr = self._advapi32.GetSidSubAuthority(sid, index)
            return int(rid_ptr.contents.value) if rid_ptr else None
        finally:
            if token:
                self._kernel32.CloseHandle(token)
            if should_close_process:
                self._kernel32.CloseHandle(process)

    def _monitor_metadata(self, hwnd: int) -> tuple[str | None, int | None]:
        monitor_from_window = getattr(self._user32, "MonitorFromWindow", None)
        get_monitor_info = getattr(self._user32, "GetMonitorInfoW", None)
        if not callable(monitor_from_window) or not callable(get_monitor_info):
            return None, None
        monitor = monitor_from_window(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None, None
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not get_monitor_info(monitor, ctypes.byref(info)):
            return None, None
        display_id = str(info.szDevice).strip() or None
        get_dpi = getattr(self._user32, "GetDpiForWindow", None)
        dpi = int(get_dpi(hwnd)) if callable(get_dpi) else 0
        return display_id, (dpi if dpi > 0 else None)

    def _display_ids_for_bounds(self, bounds: WindowBounds) -> list[str]:
        enum_display_monitors = getattr(self._user32, "EnumDisplayMonitors", None)
        get_monitor_info = getattr(self._user32, "GetMonitorInfoW", None)
        if not callable(enum_display_monitors) or not callable(get_monitor_info):
            return []
        rect = wintypes.RECT(
            int(round(bounds.x)),
            int(round(bounds.y)),
            int(round(bounds.x + bounds.width)),
            int(round(bounds.y + bounds.height)),
        )
        values: list[str] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        @callback_type
        def callback(
            monitor: int,
            _hdc: int,
            _rect: ctypes.POINTER(wintypes.RECT),
            _lparam: int,
        ) -> bool:
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
            if get_monitor_info(monitor, ctypes.byref(info)):
                value = str(info.szDevice).strip()
                if value and value not in values:
                    values.append(value)
            return True

        if not enum_display_monitors(None, ctypes.byref(rect), callback, 0):
            return []
        return values

    def support_status(self) -> dict[str, Any]:
        return {
            "supported": True,
            "platform": self.platform,
            "driver": self.name,
            "capture": "gdi_printwindow",
            "input": "win32_user_input",
            "accessibility": "not_implemented",
            "dpi_awareness": self._dpi_awareness,
        }

    def _window_text(self, hwnd: int) -> str:
        length = max(0, int(self._user32.GetWindowTextLengthW(hwnd)))
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    def _process_identity(self, pid: int) -> tuple[str, str, bool, str]:
        cached = self._identity_cache.get(pid)
        if cached is not None:
            return cached
        handle = self._kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            value = ("", "", False, f"pid-{pid}")
            self._identity_cache[pid] = value
            return value
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                value = ("", "", False, f"pid-{pid}")
            else:
                raw_path = buffer.value
                path = Path(raw_path)
                name = path.stem or path.name or f"pid-{pid}"
                try:
                    stat = path.stat()
                    normalized = str(path.resolve())
                    fingerprint = self._binary_fingerprint(
                        path,
                        size=int(stat.st_size),
                        mtime_ns=int(stat.st_mtime_ns),
                    )
                    value = (
                        normalized.lower(),
                        fingerprint,
                        bool(fingerprint),
                        name,
                    )
                except OSError:
                    value = (raw_path.lower(), "", False, name)
        finally:
            self._kernel32.CloseHandle(handle)
        self._identity_cache[pid] = value
        return value

    def _target_from_window(self, hwnd: int) -> DesktopTarget | None:
        if not hwnd or not self._user32.IsWindowVisible(hwnd):
            return None
        owner_window_id = int(self._user32.GetWindow(hwnd, _GW_OWNER) or 0)
        if int(self._user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)) & _WS_EX_TOOLWINDOW:
            return None
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 64 or height < 48:
            return None
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        owner_pid = int(pid.value)
        if owner_pid <= 0 or owner_pid in self._excluded_pids:
            return None
        app_id, fingerprint, persistent, app_name = self._process_identity(owner_pid)
        executable_name = Path(app_id).name.casefold() if app_id else app_name.casefold()
        protected_reason = (
            "system_authorization_surface"
            if executable_name in _PROTECTED_CONTROL_EXECUTABLES
            else ""
        )
        return DesktopTarget(
            window_id=int(hwnd),
            owner_pid=owner_pid,
            application_name=app_name,
            window_title=self._window_text(hwnd),
            bounds=WindowBounds(float(rect.left), float(rect.top), float(width), float(height)),
            onscreen=not bool(self._user32.IsIconic(hwnd)),
            application_id=app_id,
            application_identity_fingerprint=fingerprint,
            persistent_authorization_supported=(persistent and not protected_reason),
            owner_window_id=owner_window_id,
            relationship="owned_dialog" if owner_window_id else "top_level",
            control_protected_reason=protected_reason,
        )

    def list_targets(self, *, max_results: int) -> list[DesktopTarget]:
        values: list[DesktopTarget] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            target = self._target_from_window(int(hwnd))
            if target is not None:
                values.append(target)
            return len(values) < max_results

        if not self._user32.EnumWindows(callback, 0):
            error = ctypes.get_last_error()
            if error:
                raise HostCapabilityError(
                    f"Windows 无法枚举桌面窗口，Win32 error={error}。",
                    code="DESKTOP_TARGET_ENUMERATION_FAILED",
                    stage="target",
                )
        return values[:max_results]

    def find_target(self, target: DesktopTarget) -> DesktopTarget | None:
        current = self._target_from_window(int(target.window_id))
        if current is None:
            return None
        if current.owner_pid != target.owner_pid:
            return None
        if target.application_id and current.application_id != target.application_id:
            return None
        if (
            target.application_identity_fingerprint
            and current.application_identity_fingerprint != target.application_identity_fingerprint
        ):
            return None
        return current

    def check_observe_permission(self) -> bool | None:
        return True

    def check_control_permission(self) -> bool | None:
        desktop_name = self._input_desktop_name()
        if desktop_name and desktop_name.casefold() != "default":
            return False
        # Windows has no global Accessibility-style grant equivalent. Whether
        # SendInput is accepted depends on the specific target's integrity
        # level/UIPI boundary, so a normal input desktop is intentionally
        # reported as unknown instead of globally granted.
        return None

    def check_target_control_permission(self, target: DesktopTarget) -> bool | None:
        if target.control_protected_reason:
            return False
        global_status = self.check_control_permission()
        if global_status is False:
            return False
        target_rid = self._integrity_rid_for_process(target.owner_pid)
        current_rid = self._current_integrity_rid
        if target_rid is None or current_rid is None:
            return None
        return target_rid <= current_rid

    def _ensure_target_control(self, target: DesktopTarget) -> None:
        status = self.check_target_control_permission(target)
        if status is False:
            raise HostCapabilityError(
                "Windows 拒绝向该目标发送 Desktop 输入；目标可能位于更高完整性级别、安全桌面或系统授权界面。",
                code="DESKTOP_TARGET_CONTROL_BLOCKED",
                stage="input",
            )

    def capture(self, target: DesktopTarget) -> dict[str, Any]:
        current = self.find_target(target)
        if current is None:
            raise HostCapabilityError("Windows Desktop 目标已消失。", code="DESKTOP_TARGET_GONE", stage="capture")
        if not current.onscreen:
            raise HostCapabilityError("Windows Desktop 目标已最小化。", code="DESKTOP_WINDOW_NOT_VISIBLE", stage="capture")
        width = max(1, int(round(current.bounds.width)))
        height = max(1, int(round(current.bounds.height)))
        window_dc = self._user32.GetDC(current.window_id)
        if not window_dc:
            raise HostCapabilityError("无法获取 Windows 目标窗口 DC。", code="DESKTOP_CAPTURE_FAILED", stage="capture")
        memory_dc = self._gdi32.CreateCompatibleDC(window_dc)
        bitmap = self._gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not memory_dc or not bitmap:
            if memory_dc:
                self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(current.window_id, window_dc)
            raise HostCapabilityError("无法创建 Windows 截图缓冲区。", code="DESKTOP_CAPTURE_FAILED", stage="capture")
        old_object = self._gdi32.SelectObject(memory_dc, bitmap)
        try:
            rendered = bool(self._user32.PrintWindow(current.window_id, memory_dc, _PW_RENDERFULLCONTENT))
            if not rendered:
                rendered = bool(self._gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, _SRCCOPY))
            if not rendered:
                raise HostCapabilityError("Windows PrintWindow/BitBlt 均失败。", code="DESKTOP_CAPTURE_FAILED", stage="capture")
            info = _BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = _BI_RGB
            raw = ctypes.create_string_buffer(width * height * 4)
            rows = self._gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, ctypes.byref(info), _DIB_RGB_COLORS)
            if rows != height:
                raise HostCapabilityError("Windows GetDIBits 返回不完整截图。", code="DESKTOP_CAPTURE_FAILED", stage="capture")
            try:
                from PIL import Image
            except ImportError as exc:
                raise HostCapabilityError("Windows Desktop 截图需要 Pillow。", code="DESKTOP_DRIVER_UNAVAILABLE", stage="capture") from exc
            image = Image.frombuffer("RGB", (width, height), raw.raw, "raw", "BGRX", 0, 1)
            output = io.BytesIO()
            image.save(output, format="PNG")
            data = output.getvalue()
        finally:
            self._gdi32.SelectObject(memory_dc, old_object)
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(current.window_id, window_dc)
        display_id, dpi = self._monitor_metadata(current.window_id)
        display_ids = self._display_ids_for_bounds(current.bounds)
        if not display_ids and display_id:
            display_ids = [display_id]
        if display_id is None and len(display_ids) == 1:
            display_id = display_ids[0]
        dpi_scale = (float(dpi) / _DEFAULT_DPI) if dpi else None
        return {
            "data_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "image/png",
            "image": {"width": width, "height": height},
            "window_bounds": current.bounds.to_dict(),
            "display_id": display_id,
            "display_ids": display_ids,
            "display_id_status": (
                "resolved"
                if len(display_ids) == 1
                else "multiple"
                if len(display_ids) > 1
                else "unavailable"
            ),
            "dpi": {
                "value": dpi,
                "scale": dpi_scale,
                "awareness": self._dpi_awareness,
            },
            "coordinate_mapping": {
                "image_space": "image_pixels",
                "input_space": "global_screen_pixels",
                "scale_x": current.bounds.width / width,
                "scale_y": current.bounds.height / height,
                "offset_x": current.bounds.x,
                "offset_y": current.bounds.y,
            },
        }

    def is_focused(self, target: DesktopTarget) -> bool | None:
        foreground = int(self._user32.GetForegroundWindow() or 0)
        return foreground == int(target.window_id)

    def _mouse_click_flags(self, button: str) -> tuple[int, int]:
        mapping = {
            "left": (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
            "right": (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
            "middle": (_MOUSEEVENTF_MIDDLEDOWN, _MOUSEEVENTF_MIDDLEUP),
        }
        try:
            return mapping[button]
        except KeyError as exc:
            raise HostCapabilityError("Windows 不支持该鼠标按键。", code="DESKTOP_INPUT_FAILED", stage="input") from exc

    def _send_inputs(self, events: ctypes.Array[_INPUT], *, description: str) -> None:
        count = len(events)
        if count <= 0:
            return
        ctypes.set_last_error(0)
        sent = int(self._user32.SendInput(count, events, ctypes.sizeof(_INPUT)))
        if sent == count:
            return
        error = ctypes.get_last_error()
        detail = f"，Win32 error={error}" if error else ""
        raise HostCapabilityError(
            f"Windows SendInput 未能完整发送{description}（{sent}/{count}）{detail}。",
            code="DESKTOP_INPUT_FAILED",
            stage="input",
        )

    @staticmethod
    def _mouse_event_input(flags: int, data: int = 0) -> _INPUT:
        event = _INPUT()
        event.type = _INPUT_MOUSE
        event.mi = _MOUSEINPUT(
            0,
            0,
            ctypes.c_uint32(data).value,
            flags,
            0,
            0,
        )
        return event

    @staticmethod
    def _keyboard_event_input(code: int, *, key_up: bool = False) -> _INPUT:
        event = _INPUT()
        event.type = _INPUT_KEYBOARD
        event.ki = _KEYBDINPUT(
            int(code),
            0,
            _KEYEVENTF_KEYUP if key_up else 0,
            0,
            0,
        )
        return event

    def click(self, target: DesktopTarget, *, x: float, y: float, button: str, click_count: int) -> None:
        self._ensure_target_control(target)
        if not self._user32.SetCursorPos(int(round(x)), int(round(y))):
            raise HostCapabilityError("Windows 无法移动鼠标到目标坐标。", code="DESKTOP_INPUT_FAILED", stage="input")
        down, up = self._mouse_click_flags(button)
        for index in range(max(1, click_count)):
            events = (_INPUT * 2)(
                self._mouse_event_input(down),
                self._mouse_event_input(up),
            )
            self._send_inputs(events, description="鼠标点击")
            if index + 1 < click_count:
                time.sleep(0.04)

    def type_text(self, target: DesktopTarget, text: str) -> None:
        self._ensure_target_control(target)
        encoded = text.encode("utf-16-le")
        units = [
            int.from_bytes(encoded[index:index + 2], "little")
            for index in range(0, len(encoded), 2)
        ]
        for unit in units:
            events = (_INPUT * 2)()
            events[0].type = _INPUT_KEYBOARD
            events[0].ki = _KEYBDINPUT(0, unit, _KEYEVENTF_UNICODE, 0, 0)
            events[1].type = _INPUT_KEYBOARD
            events[1].ki = _KEYBDINPUT(0, unit, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, 0)
            self._send_inputs(events, description="Unicode 文本")

    @staticmethod
    def _virtual_key(name: str) -> int:
        normalized = name.strip().upper()
        named = {
            "CTRL": 0x11, "CONTROL": 0x11, "SHIFT": 0x10, "ALT": 0x12,
            "META": 0x5B, "WIN": 0x5B, "ENTER": 0x0D, "RETURN": 0x0D,
            "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08,
            "DELETE": 0x2E, "SPACE": 0x20, "LEFT": 0x25, "UP": 0x26,
            "RIGHT": 0x27, "DOWN": 0x28, "HOME": 0x24, "END": 0x23,
            "PAGEUP": 0x21, "PAGEDOWN": 0x22,
        }
        if normalized in named:
            return named[normalized]
        if normalized.startswith("F") and normalized[1:].isdigit():
            number = int(normalized[1:])
            if 1 <= number <= 24:
                return 0x6F + number
        if len(normalized) == 1 and normalized.isalnum():
            return ord(normalized)
        raise HostCapabilityError(f"Windows 不支持按键 {name!r}。", code="DESKTOP_INPUT_FAILED", stage="input")

    def keypress(self, target: DesktopTarget, key: str) -> None:
        self._ensure_target_control(target)
        parts = [item.strip() for item in key.replace("-", "+").split("+") if item.strip()]
        if not parts:
            raise HostCapabilityError("Windows keypress 缺少有效按键。", code="DESKTOP_INPUT_FAILED", stage="input")
        codes = [self._virtual_key(item) for item in parts]
        sequence = [
            self._keyboard_event_input(code)
            for code in codes
        ] + [
            self._keyboard_event_input(code, key_up=True)
            for code in reversed(codes)
        ]
        events = (_INPUT * len(sequence))(*sequence)
        self._send_inputs(events, description="组合键")

    def scroll(self, target: DesktopTarget, *, delta_x: int, delta_y: int, x: float | None, y: float | None) -> None:
        self._ensure_target_control(target)
        if x is not None and y is not None:
            if not self._user32.SetCursorPos(int(round(x)), int(round(y))):
                raise HostCapabilityError("Windows 无法移动鼠标到滚动坐标。", code="DESKTOP_INPUT_FAILED", stage="input")
        sequence: list[_INPUT] = []
        if delta_y:
            sequence.append(
                self._mouse_event_input(_MOUSEEVENTF_WHEEL, _signed_wheel(delta_y))
            )
        if delta_x:
            sequence.append(
                self._mouse_event_input(_MOUSEEVENTF_HWHEEL, _signed_wheel(delta_x))
            )
        if sequence:
            events = (_INPUT * len(sequence))(*sequence)
            self._send_inputs(events, description="滚轮输入")

    def drag(self, target: DesktopTarget, *, path: list[tuple[float, float]], button: str, duration_ms: int) -> None:
        self._ensure_target_control(target)
        if len(path) < 2:
            raise HostCapabilityError("Windows drag path 至少需要两个点。", code="DESKTOP_INPUT_FAILED", stage="input")
        down, up = self._mouse_click_flags(button)
        first_x, first_y = path[0]
        if not self._user32.SetCursorPos(int(round(first_x)), int(round(first_y))):
            raise HostCapabilityError("Windows 无法移动鼠标到拖拽起点。", code="DESKTOP_INPUT_FAILED", stage="input")
        press = (_INPUT * 1)(self._mouse_event_input(down))
        self._send_inputs(press, description="拖拽按下")
        try:
            interval = (max(0, duration_ms) / 1000.0) / max(1, len(path) - 1)
            for x, y in path[1:]:
                if not self._user32.SetCursorPos(int(round(x)), int(round(y))):
                    raise HostCapabilityError(
                        "Windows 无法移动鼠标到拖拽路径坐标。",
                        code="DESKTOP_INPUT_FAILED",
                        stage="input",
                    )
                if interval:
                    time.sleep(interval)
        finally:
            release = (_INPUT * 1)(self._mouse_event_input(up))
            self._send_inputs(release, description="拖拽释放")

    def accessibility_elements(self, target: DesktopTarget, *, max_elements: int) -> dict[str, Any]:
        return {
            "supported": False,
            "reason": "windows_uia_not_available_in_native_driver_yet",
            "elements": [],
        }


__all__ = ["WindowsDesktopDriver"]
