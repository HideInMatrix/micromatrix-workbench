from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ...base import HostCapabilityError
from .base import DesktopControlDecision, DesktopTarget, WindowBounds


_UTF8 = 0x08000100
_WINDOW_OPTION_ALL = 0
_WINDOW_OPTION_INCLUDING_WINDOW = 1 << 3
_WINDOW_IMAGE_DEFAULT = 0
_EVENT_TAP_HID = 0
_SCROLL_UNIT_PIXEL = 0


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _framework(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if not path:
        raise HostCapabilityError(
            f"无法加载 macOS {name} framework。",
            code="DESKTOP_DRIVER_UNAVAILABLE",
            stage="driver_init",
        )
    return ctypes.CDLL(path)


class MacOSDesktopDriver:
    name = "macos_coregraphics"
    platform = "darwin"

    def __init__(self) -> None:
        self._cf = _framework("CoreFoundation")
        self._cg = _framework("CoreGraphics")
        self._app = _framework("ApplicationServices")
        self._imageio = _framework("ImageIO")
        self._libproc = self._load_libproc()
        self._configure_core_foundation()
        self._configure_core_graphics()
        self._configure_imageio()
        self._configure_accessibility()
        self._window_keys = {
            name: self._global_pointer(name)
            for name in (
                "kCGWindowNumber",
                "kCGWindowOwnerPID",
                "kCGWindowOwnerName",
                "kCGWindowName",
                "kCGWindowBounds",
                "kCGWindowLayer",
                "kCGWindowIsOnscreen",
                "kCGWindowAlpha",
            )
        }
        self._excluded_pids = {os.getpid(), os.getppid()}
        self._process_identity_cache: dict[int, tuple[str, str, bool]] = {}
        self._binary_fingerprint_cache: dict[tuple[str, int, int], str] = {}

    @staticmethod
    def _load_libproc() -> ctypes.CDLL | None:
        path = ctypes.util.find_library("proc")
        if not path:
            return None
        library = ctypes.CDLL(path)
        library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        library.proc_pidpath.restype = ctypes.c_int
        return library

    def _binary_fingerprint(self, path: Path, *, size: int, mtime_ns: int) -> str:
        normalized = str(path.resolve())
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

    def _process_identity(self, pid: int) -> tuple[str, str, bool]:
        cached = self._process_identity_cache.get(pid)
        if cached is not None:
            return cached
        library = self._libproc
        if library is None:
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        buffer = ctypes.create_string_buffer(4096)
        length = int(library.proc_pidpath(pid, buffer, len(buffer)))
        if length <= 0:
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        try:
            executable = Path(buffer.value.decode("utf-8")).resolve()
        except (OSError, UnicodeDecodeError):
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        bundle: Path | None = None
        for candidate in (executable, *executable.parents):
            if candidate.suffix.lower() == ".app":
                bundle = candidate
                break
        if bundle is None:
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        info_path = bundle / "Contents" / "Info.plist"
        try:
            with info_path.open("rb") as handle:
                info = plistlib.load(handle)
            bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
            stat = executable.stat()
        except (OSError, plistlib.InvalidFileException):
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        if not bundle_id:
            value = ("", "", False)
            self._process_identity_cache[pid] = value
            return value
        binary_hash = self._binary_fingerprint(
            executable,
            size=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
        )
        if not binary_hash:
            value = (bundle_id, "", False)
        else:
            identity_material = "\0".join(
                (bundle_id, str(bundle), str(executable), binary_hash)
            ).encode("utf-8", "surrogateescape")
            fingerprint = hashlib.sha256(identity_material).hexdigest()
            value = (bundle_id, fingerprint, True)
        self._process_identity_cache[pid] = value
        return value

    def _configure_core_foundation(self) -> None:
        cf = self._cf
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFDataCreateMutable.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFDataCreateMutable.restype = ctypes.c_void_p
        cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)

    def _configure_core_graphics(self) -> None:
        cg = self._cg
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        cg.CGRectMakeWithDictionaryRepresentation.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CGRect)]
        cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
        if hasattr(cg, "CGPreflightScreenCaptureAccess"):
            cg.CGPreflightScreenCaptureAccess.argtypes = []
            cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        if hasattr(cg, "CGWindowListCreateImage"):
            cg.CGWindowListCreateImage.argtypes = [
                _CGRect,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            cg.CGWindowListCreateImage.restype = ctypes.c_void_p
        cg.CGImageGetWidth.argtypes = [ctypes.c_void_p]
        cg.CGImageGetWidth.restype = ctypes.c_size_t
        cg.CGImageGetHeight.argtypes = [ctypes.c_void_p]
        cg.CGImageGetHeight.restype = ctypes.c_size_t
        if hasattr(cg, "CGGetDisplaysWithRect"):
            cg.CGGetDisplaysWithRect.argtypes = [
                _CGRect,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            cg.CGGetDisplaysWithRect.restype = ctypes.c_int32
        cg.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            _CGPoint,
            ctypes.c_uint32,
        ]
        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventKeyboardSetUnicodeString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_uint16),
        ]
        cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        if hasattr(cg, "CGEventSetIntegerValueField"):
            cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        # CGEventCreateScrollWheelEvent is variadic. Declare only the fixed prefix.
        cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p

    def _configure_imageio(self) -> None:
        imageio = self._imageio
        imageio.CGImageDestinationCreateWithData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
        ]
        imageio.CGImageDestinationCreateWithData.restype = ctypes.c_void_p
        imageio.CGImageDestinationAddImage.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        imageio.CGImageDestinationFinalize.argtypes = [ctypes.c_void_p]
        imageio.CGImageDestinationFinalize.restype = ctypes.c_bool

    def _configure_accessibility(self) -> None:
        if hasattr(self._app, "AXIsProcessTrusted"):
            self._app.AXIsProcessTrusted.argtypes = []
            self._app.AXIsProcessTrusted.restype = ctypes.c_bool

    def _global_pointer(self, name: str) -> int:
        try:
            return int(ctypes.c_void_p.in_dll(self._cg, name).value or 0)
        except ValueError as exc:
            raise HostCapabilityError(
                f"CoreGraphics 缺少窗口元数据符号 {name}。",
                code="DESKTOP_DRIVER_UNAVAILABLE",
                stage="driver_init",
            ) from exc

    def _dict_value(self, dictionary: int, key: str) -> int:
        pointer = self._window_keys.get(key) or 0
        if not pointer:
            return 0
        return int(self._cf.CFDictionaryGetValue(dictionary, pointer) or 0)

    def _cf_string(self, value: int) -> str:
        if not value:
            return ""
        buffer = ctypes.create_string_buffer(16_384)
        if not self._cf.CFStringGetCString(value, buffer, len(buffer), _UTF8):
            return ""
        return buffer.value.decode("utf-8", "replace")

    def _cf_int(self, value: int) -> int:
        if not value:
            return 0
        target = ctypes.c_longlong()
        if not self._cf.CFNumberGetValue(value, 4, ctypes.byref(target)):
            return 0
        return int(target.value)

    def _cf_float(self, value: int) -> float:
        if not value:
            return 0.0
        target = ctypes.c_double()
        if not self._cf.CFNumberGetValue(value, 13, ctypes.byref(target)):
            return 0.0
        return float(target.value)

    def _cf_bool(self, value: int) -> bool:
        return bool(value and self._cf.CFBooleanGetValue(value))

    def _bounds(self, dictionary: int) -> WindowBounds | None:
        value = self._dict_value(dictionary, "kCGWindowBounds")
        if not value:
            return None
        rect = _CGRect()
        if not self._cg.CGRectMakeWithDictionaryRepresentation(value, ctypes.byref(rect)):
            return None
        return WindowBounds(
            x=float(rect.origin.x),
            y=float(rect.origin.y),
            width=float(rect.size.width),
            height=float(rect.size.height),
        )

    def _window_records(self) -> list[DesktopTarget]:
        array = self._cg.CGWindowListCopyWindowInfo(_WINDOW_OPTION_ALL, 0)
        if not array:
            raise HostCapabilityError(
                "当前进程无法访问 macOS WindowServer 窗口列表；Desktop Computer Use 必须运行在可访问登录桌面的 Workbench Desktop Host 上。",
                code="DESKTOP_WINDOW_SERVER_UNAVAILABLE",
                stage="targets",
            )
        try:
            count = int(self._cf.CFArrayGetCount(array))
            result: list[DesktopTarget] = []
            for index in range(count):
                raw = int(self._cf.CFArrayGetValueAtIndex(array, index) or 0)
                if not raw:
                    continue
                layer = self._cf_int(self._dict_value(raw, "kCGWindowLayer"))
                if layer != 0:
                    continue
                owner_pid = self._cf_int(self._dict_value(raw, "kCGWindowOwnerPID"))
                if owner_pid <= 0 or owner_pid in self._excluded_pids:
                    continue
                window_id = self._cf_int(self._dict_value(raw, "kCGWindowNumber"))
                bounds = self._bounds(raw)
                if window_id <= 0 or bounds is None or bounds.width < 48 or bounds.height < 48:
                    continue
                alpha = self._cf_float(self._dict_value(raw, "kCGWindowAlpha"))
                if alpha <= 0:
                    continue
                owner_name = self._cf_string(self._dict_value(raw, "kCGWindowOwnerName")).strip()
                if not owner_name:
                    continue
                title = self._cf_string(self._dict_value(raw, "kCGWindowName")).strip()
                onscreen = self._cf_bool(self._dict_value(raw, "kCGWindowIsOnscreen"))
                application_id, identity_fingerprint, identity_verified = self._process_identity(owner_pid)
                result.append(
                    DesktopTarget(
                        window_id=window_id,
                        owner_pid=owner_pid,
                        application_name=owner_name,
                        window_title=title,
                        bounds=bounds,
                        onscreen=onscreen,
                        application_id=application_id,
                        application_identity_fingerprint=identity_fingerprint,
                        application_identity_verified=identity_verified,
                    )
                )
            return result
        finally:
            self._cf.CFRelease(array)

    def support_status(self) -> dict[str, Any]:
        observe = self.check_observe_permission()
        control = self.check_control_permission()
        return {
            "supported": True,
            "platform": self.platform,
            "driver": self.name,
            "screen_capture": (
                "granted" if observe is True else "denied" if observe is False else "unknown"
            ),
            "accessibility_control": (
                "granted" if control is True else "denied" if control is False else "unknown"
            ),
            "capabilities": {
                "window_discovery": True,
                "window_capture": True,
                "coordinate_input": True,
                "accessibility_elements": False,
            },
        }

    def list_targets(self, *, max_results: int) -> list[DesktopTarget]:
        limit = max(1, min(int(max_results), 100))
        return self._window_records()[:limit]

    def find_target(self, target: DesktopTarget) -> DesktopTarget | None:
        for current in self._window_records():
            if current.window_id != target.window_id:
                continue
            if current.owner_pid != target.owner_pid or current.application_name != target.application_name:
                return None
            return current
        return None

    def check_observe_permission(self) -> bool | None:
        fn = getattr(self._cg, "CGPreflightScreenCaptureAccess", None)
        if not callable(fn):
            return None
        return bool(fn())

    def check_control_permission(self) -> bool | None:
        fn = getattr(self._app, "AXIsProcessTrusted", None)
        if not callable(fn):
            return None
        return bool(fn())

    def control_decision(self, target: DesktopTarget) -> DesktopControlDecision:
        control = self.check_control_permission()
        if control is False:
            return DesktopControlDecision(
                False,
                boundary="accessibility_permission",
                code="DESKTOP_ACCESSIBILITY_PERMISSION_REQUIRED",
                stage="system_permission",
                message="macOS 尚未授予 Workbench 桌面控制所需的辅助功能权限。",
            )
        return DesktopControlDecision(
            control,
            boundary="accessibility_permission" if control is None else "standard",
        )

    def _encode_image(self, image: int) -> bytes:
        data = self._cf.CFDataCreateMutable(None, 0)
        uti = self._cf.CFStringCreateWithCString(None, b"public.png", _UTF8)
        destination = 0
        try:
            if not data or not uti:
                raise HostCapabilityError(
                    "无法创建 PNG 编码缓冲区。",
                    code="DESKTOP_CAPTURE_FAILED",
                    stage="capture",
                )
            destination = int(self._imageio.CGImageDestinationCreateWithData(data, uti, 1, None) or 0)
            if not destination:
                raise HostCapabilityError(
                    "无法创建 PNG 编码器。",
                    code="DESKTOP_CAPTURE_FAILED",
                    stage="capture",
                )
            self._imageio.CGImageDestinationAddImage(destination, image, None)
            if not self._imageio.CGImageDestinationFinalize(destination):
                raise HostCapabilityError(
                    "PNG 编码失败。",
                    code="DESKTOP_CAPTURE_FAILED",
                    stage="capture",
                )
            length = int(self._cf.CFDataGetLength(data))
            pointer = self._cf.CFDataGetBytePtr(data)
            if length <= 0 or not pointer:
                raise HostCapabilityError(
                    "PNG 编码结果为空。",
                    code="DESKTOP_CAPTURE_FAILED",
                    stage="capture",
                )
            return ctypes.string_at(pointer, length)
        finally:
            if destination:
                self._cf.CFRelease(destination)
            if uti:
                self._cf.CFRelease(uti)
            if data:
                self._cf.CFRelease(data)

    def _capture_coregraphics(self, target: DesktopTarget) -> tuple[bytes, int, int] | None:
        fn = getattr(self._cg, "CGWindowListCreateImage", None)
        if not callable(fn):
            return None
        rect = _CGRect(
            _CGPoint(target.bounds.x, target.bounds.y),
            _CGSize(target.bounds.width, target.bounds.height),
        )
        image = int(
            fn(
                rect,
                _WINDOW_OPTION_INCLUDING_WINDOW,
                target.window_id,
                _WINDOW_IMAGE_DEFAULT,
            )
            or 0
        )
        if not image:
            return None
        try:
            width = int(self._cg.CGImageGetWidth(image))
            height = int(self._cg.CGImageGetHeight(image))
            if width <= 0 or height <= 0:
                return None
            return self._encode_image(image), width, height
        finally:
            self._cf.CFRelease(image)

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return 0, 0

    def _capture_screencapture(self, target: DesktopTarget) -> tuple[bytes, int, int] | None:
        executable = shutil.which("screencapture")
        if not executable:
            return None
        completed = subprocess.run(
            [executable, "-x", "-o", f"-l{target.window_id}", "-t", "png", "-"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            return None
        width, height = self._png_dimensions(completed.stdout)
        if width <= 0 or height <= 0:
            return None
        return completed.stdout, width, height

    def capture(self, target: DesktopTarget) -> dict[str, Any]:
        current = self.find_target(target)
        if current is None:
            raise HostCapabilityError(
                "Desktop 目标窗口已关闭或身份已变化。",
                code="DESKTOP_TARGET_GONE",
                stage="capture",
            )
        if not current.onscreen:
            raise HostCapabilityError(
                "Desktop 目标窗口当前不在屏幕上，无法可靠采集。",
                code="DESKTOP_WINDOW_NOT_VISIBLE",
                stage="capture",
            )
        permission = self.check_observe_permission()
        if permission is False:
            raise HostCapabilityError(
                "macOS 尚未授予 Workbench 屏幕录制/屏幕与系统音频访问权限。",
                code="DESKTOP_SCREEN_PERMISSION_REQUIRED",
                stage="system_permission",
            )
        captured = self._capture_coregraphics(current) or self._capture_screencapture(current)
        if captured is None:
            raise HostCapabilityError(
                "无法采集 Desktop 目标窗口；请检查系统屏幕访问权限和窗口可见状态。",
                code="DESKTOP_CAPTURE_FAILED",
                stage="capture",
            )
        data, width, height = captured
        display_ids = self._display_ids_for_bounds(current.bounds)
        return {
            "data_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "image/png",
            "image": {"width": width, "height": height},
            "window_bounds": current.bounds.to_dict(),
            "display_id": display_ids[0] if display_ids else None,
            "display_ids": display_ids,
            "display_id_status": (
                "resolved"
                if len(display_ids) == 1
                else "multiple"
                if len(display_ids) > 1
                else "unavailable"
            ),
            "coordinate_mapping": {
                "image_space": "image_pixels",
                "input_space": "global_screen_points",
                "scale_x": current.bounds.width / width,
                "scale_y": current.bounds.height / height,
                "offset_x": current.bounds.x,
                "offset_y": current.bounds.y,
            },
        }

    def _display_ids_for_bounds(self, bounds: WindowBounds) -> list[int]:
        fn = getattr(self._cg, "CGGetDisplaysWithRect", None)
        if not callable(fn):
            return []
        rect = _CGRect(
            _CGPoint(bounds.x, bounds.y),
            _CGSize(bounds.width, bounds.height),
        )
        displays = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32(0)
        error = int(fn(rect, len(displays), displays, ctypes.byref(count)))
        if error != 0:
            return []
        return [
            int(displays[index])
            for index in range(min(int(count.value), len(displays)))
        ]

    def is_focused(self, target: DesktopTarget) -> bool | None:
        # A normal macOS app can remain the frontmost application while an
        # always-on-top utility window from another process is visually above
        # it.  Using the first layer-0 WindowServer record therefore produces
        # false negatives for applications such as Blender whenever a floating
        # utility window is present.  NSWorkspace exposes the actual frontmost
        # application chosen by AppKit, which is the security boundary we need
        # before emitting keyboard/mouse input.
        try:
            from AppKit import NSWorkspace

            frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
            if frontmost is not None:
                if int(frontmost.processIdentifier()) != target.owner_pid:
                    return False
                # Preserve window-level isolation.  Once the frontmost app is
                # confirmed, compare only that application's leading onscreen
                # WindowServer record with the authorized target.  Floating
                # windows owned by other applications no longer cause false
                # negatives, while another Blender window still cannot inherit
                # this target's authorization.
                for current in self._window_records():
                    if current.onscreen and current.owner_pid == target.owner_pid:
                        return current.identity == target.identity
                return None
        except Exception:
            # Keep a fail-closed fallback for source/test environments where
            # PyObjC/AppKit is unavailable.
            pass
        for current in self._window_records():
            if not current.onscreen:
                continue
            return current.identity == target.identity
        return None

    def focus_target(self, target: DesktopTarget) -> bool:
        """Bring the explicitly authorized target application to foreground.

        The provider still performs a full window-level ``is_focused`` check
        after this call, so activating an application cannot make a different
        window inherit the attached target's authorization.
        """
        try:
            from AppKit import (
                NSApplicationActivateAllWindows,
                NSApplicationActivateIgnoringOtherApps,
                NSRunningApplication,
            )

            application = NSRunningApplication.runningApplicationWithProcessIdentifier_(
                target.owner_pid
            )
            if application is None:
                return False
            options = (
                NSApplicationActivateAllWindows
                | NSApplicationActivateIgnoringOtherApps
            )
            return bool(application.activateWithOptions_(options))
        except Exception:
            return False

    def _ensure_control_permission(self) -> None:
        permission = self.check_control_permission()
        if permission is False:
            raise HostCapabilityError(
                "macOS 尚未授予 Workbench 辅助功能控制权限。",
                code="DESKTOP_ACCESSIBILITY_PERMISSION_REQUIRED",
                stage="system_permission",
            )

    def _post_mouse(self, event_type: int, x: float, y: float, button: int, *, click_count: int = 1) -> None:
        event = self._cg.CGEventCreateMouseEvent(None, event_type, _CGPoint(x, y), button)
        if not event:
            raise HostCapabilityError(
                "无法创建 macOS 鼠标事件。",
                code="DESKTOP_INPUT_FAILED",
                stage="input",
            )
        try:
            setter = getattr(self._cg, "CGEventSetIntegerValueField", None)
            if click_count > 1 and callable(setter):
                setter(event, 1, click_count)
            self._cg.CGEventPost(_EVENT_TAP_HID, event)
        finally:
            self._cf.CFRelease(event)

    def click(
        self,
        target: DesktopTarget,
        *,
        x: float,
        y: float,
        button: str,
        click_count: int,
    ) -> None:
        self._ensure_control_permission()
        button_map = {
            "left": (0, 1, 2),
            "right": (1, 3, 4),
            "middle": (2, 25, 26),
        }
        button_id, down_type, up_type = button_map.get(button, button_map["left"])
        for index in range(max(1, min(click_count, 3))):
            self._post_mouse(down_type, x, y, button_id, click_count=index + 1)
            self._post_mouse(up_type, x, y, button_id, click_count=index + 1)
            if index + 1 < click_count:
                time.sleep(0.06)

    def _post_keycode(self, keycode: int, *, flags: int = 0) -> None:
        for is_down in (True, False):
            event = self._cg.CGEventCreateKeyboardEvent(None, keycode, is_down)
            if not event:
                raise HostCapabilityError(
                    "无法创建 macOS 键盘事件。",
                    code="DESKTOP_INPUT_FAILED",
                    stage="input",
                )
            try:
                if flags:
                    self._cg.CGEventSetFlags(event, flags)
                self._cg.CGEventPost(_EVENT_TAP_HID, event)
            finally:
                self._cf.CFRelease(event)

    def type_text(self, target: DesktopTarget, text: str) -> None:
        self._ensure_control_permission()
        if self.is_focused(target) is not True:
            raise HostCapabilityError(
                "目标应用当前不在前台；请先在该窗口执行一次明确点击后再输入文本。",
                code="DESKTOP_TARGET_NOT_FOCUSED",
                stage="focus",
            )
        for start in range(0, len(text), 20):
            chunk = text[start : start + 20]
            raw = chunk.encode("utf-16-le")
            units = len(raw) // 2
            if units == 0:
                continue
            values = (ctypes.c_uint16 * units).from_buffer_copy(raw)
            down = self._cg.CGEventCreateKeyboardEvent(None, 0, True)
            up = self._cg.CGEventCreateKeyboardEvent(None, 0, False)
            if not down or not up:
                if down:
                    self._cf.CFRelease(down)
                if up:
                    self._cf.CFRelease(up)
                raise HostCapabilityError(
                    "无法创建 macOS 文本输入事件。",
                    code="DESKTOP_INPUT_FAILED",
                    stage="input",
                )
            try:
                self._cg.CGEventKeyboardSetUnicodeString(down, units, values)
                self._cg.CGEventKeyboardSetUnicodeString(up, units, values)
                self._cg.CGEventPost(_EVENT_TAP_HID, down)
                self._cg.CGEventPost(_EVENT_TAP_HID, up)
            finally:
                self._cf.CFRelease(down)
                self._cf.CFRelease(up)

    @staticmethod
    def _keycodes() -> dict[str, int]:
        return {
            "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7,
            "C": 8, "V": 9, "B": 11, "Q": 12, "W": 13, "E": 14, "R": 15,
            "Y": 16, "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
            "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
            "]": 30, "O": 31, "U": 32, "[": 33, "I": 34, "P": 35, "ENTER": 36,
            "RETURN": 36, "L": 37, "J": 38, "'": 39, "K": 40, ";": 41, "\\": 42,
            ",": 43, "/": 44, "N": 45, "M": 46, ".": 47, "TAB": 48, "SPACE": 49,
            "BACKSPACE": 51, "DELETE": 51, "ESC": 53, "ESCAPE": 53,
            "F5": 96, "F6": 97, "F7": 98, "F3": 99, "F8": 100, "F9": 101,
            "F11": 103, "F10": 109, "F12": 111, "HOME": 115, "PAGEUP": 116,
            "FORWARDDELETE": 117, "F4": 118, "END": 119, "F2": 120, "PAGEDOWN": 121,
            "F1": 122, "LEFT": 123, "ARROWLEFT": 123, "RIGHT": 124, "ARROWRIGHT": 124,
            "DOWN": 125, "ARROWDOWN": 125, "UP": 126, "ARROWUP": 126,
        }

    def keypress(self, target: DesktopTarget, key: str) -> None:
        self._ensure_control_permission()
        if self.is_focused(target) is not True:
            raise HostCapabilityError(
                "目标应用当前不在前台；请先在该窗口执行一次明确点击后再发送按键。",
                code="DESKTOP_TARGET_NOT_FOCUSED",
                stage="focus",
            )
        parts = [item.strip().upper() for item in key.split("+") if item.strip()]
        if not parts:
            raise HostCapabilityError(
                "keypress 缺少有效按键。",
                code="INVALID_DESKTOP_KEY",
                stage="validation",
            )
        modifier_flags = {
            "SHIFT": 1 << 17,
            "CTRL": 1 << 18,
            "CONTROL": 1 << 18,
            "ALT": 1 << 19,
            "OPTION": 1 << 19,
            "CMD": 1 << 20,
            "COMMAND": 1 << 20,
        }
        flags = 0
        for modifier in parts[:-1]:
            if modifier not in modifier_flags:
                raise HostCapabilityError(
                    f"不支持的 macOS 组合键修饰符: {modifier}",
                    code="INVALID_DESKTOP_KEY",
                    stage="validation",
                )
            flags |= modifier_flags[modifier]
        key_name = parts[-1]
        keycode = self._keycodes().get(key_name)
        if keycode is None:
            raise HostCapabilityError(
                f"不支持的 macOS 按键: {key_name}",
                code="INVALID_DESKTOP_KEY",
                stage="validation",
            )
        self._post_keycode(keycode, flags=flags)

    def _move_mouse(self, x: float, y: float) -> None:
        self._post_mouse(5, x, y, 0)

    def scroll(
        self,
        target: DesktopTarget,
        *,
        delta_x: int,
        delta_y: int,
        x: float | None,
        y: float | None,
    ) -> None:
        self._ensure_control_permission()
        if x is not None and y is not None:
            self._move_mouse(x, y)
        event = self._cg.CGEventCreateScrollWheelEvent(
            None,
            _SCROLL_UNIT_PIXEL,
            2,
            ctypes.c_int32(delta_y),
            ctypes.c_int32(delta_x),
        )
        if not event:
            raise HostCapabilityError(
                "无法创建 macOS 滚动事件。",
                code="DESKTOP_INPUT_FAILED",
                stage="input",
            )
        try:
            self._cg.CGEventPost(_EVENT_TAP_HID, event)
        finally:
            self._cf.CFRelease(event)

    def drag(
        self,
        target: DesktopTarget,
        *,
        path: list[tuple[float, float]],
        button: str,
        duration_ms: int,
    ) -> None:
        self._ensure_control_permission()
        if len(path) < 2:
            raise HostCapabilityError(
                "drag path 至少需要两个点。",
                code="INVALID_DESKTOP_DRAG",
                stage="validation",
            )
        button_id = 0 if button == "left" else 1
        down_type = 1 if button == "left" else 3
        drag_type = 6 if button == "left" else 7
        up_type = 2 if button == "left" else 4
        first_x, first_y = path[0]
        self._move_mouse(first_x, first_y)
        self._post_mouse(down_type, first_x, first_y, button_id)
        interval = max(0.0, duration_ms / 1000.0 / max(1, len(path) - 1))
        try:
            for x, y in path[1:]:
                if interval:
                    time.sleep(interval)
                self._post_mouse(drag_type, x, y, button_id)
        finally:
            end_x, end_y = path[-1]
            self._post_mouse(up_type, end_x, end_y, button_id)

    def accessibility_elements(
        self,
        target: DesktopTarget,
        *,
        max_elements: int,
    ) -> dict[str, Any]:
        permission = self.check_control_permission()
        return {
            "supported": False,
            "permission": (
                "granted" if permission is True else "denied" if permission is False else "unknown"
            ),
            "reason": "accessibility_tree_not_exposed_by_current_driver",
            "elements": [],
            "max_elements": max(0, min(int(max_elements), 1000)),
        }


__all__ = ["MacOSDesktopDriver"]
