from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


_CF_UTF8 = 0x08000100


class HostApplicationResolutionError(RuntimeError):
    """OS application resolution failure independent of any capability."""


@dataclass(frozen=True, slots=True)
class HostApplication:
    executable: Path
    identity: str
    source: str
    is_default: bool = False


def _bundle_executable(application: Path) -> tuple[Path, str]:
    info_path = application / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise HostApplicationResolutionError("无法读取 Application Bundle 元数据。") from exc
    executable_name = str(info.get("CFBundleExecutable") or "").strip()
    bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
    if not executable_name or not bundle_id:
        raise HostApplicationResolutionError("Application Bundle 元数据不完整。")
    executable = application / "Contents" / "MacOS" / executable_name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise HostApplicationResolutionError("Application Bundle 主程序不可执行。")
    return executable.resolve(), bundle_id


class _MacLaunchServices:
    def __init__(self) -> None:
        core_path = ctypes.util.find_library("CoreServices")
        cf_path = ctypes.util.find_library("CoreFoundation")
        if not core_path or not cf_path:
            raise HostApplicationResolutionError("macOS LaunchServices 不可用。")
        self.core = ctypes.CDLL(core_path)
        self.cf = ctypes.CDLL(cf_path)
        self._configure()

    def _configure(self) -> None:
        cf = self.cf
        core = self.core
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32,
        ]
        cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
        cf.CFURLGetFileSystemRepresentation.argtypes = [
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p, ctypes.c_long,
        ]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        core.LSCopyDefaultHandlerForURLScheme.restype = ctypes.c_void_p
        core.LSCopyDefaultHandlerForURLScheme.argtypes = [ctypes.c_void_p]
        core.LSCopyAllHandlersForURLScheme.restype = ctypes.c_void_p
        core.LSCopyAllHandlersForURLScheme.argtypes = [ctypes.c_void_p]
        core.LSCopyApplicationURLsForBundleIdentifier.restype = ctypes.c_void_p
        core.LSCopyApplicationURLsForBundleIdentifier.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]

    def string(self, value: str) -> ctypes.c_void_p:
        pointer = self.cf.CFStringCreateWithCString(
            None, value.encode("utf-8"), _CF_UTF8
        )
        if not pointer:
            raise HostApplicationResolutionError("无法创建 LaunchServices 查询字符串。")
        return ctypes.c_void_p(pointer)

    def string_value(self, pointer: int | ctypes.c_void_p) -> str:
        buffer = ctypes.create_string_buffer(4096)
        ok = self.cf.CFStringGetCString(
            pointer, ctypes.cast(buffer, ctypes.c_void_p), len(buffer), _CF_UTF8
        )
        return buffer.value.decode("utf-8") if ok else ""

    def url_path(self, pointer: int | ctypes.c_void_p) -> Path | None:
        buffer = ctypes.create_string_buffer(8192)
        ok = self.cf.CFURLGetFileSystemRepresentation(
            pointer, True, ctypes.cast(buffer, ctypes.c_void_p), len(buffer)
        )
        if not ok:
            return None
        try:
            return Path(buffer.value.decode("utf-8")).resolve()
        except (OSError, UnicodeDecodeError):
            return None

    def handlers(self, scheme_name: str) -> tuple[str, list[str]]:
        scheme = self.string(scheme_name)
        try:
            default_ptr = self.core.LSCopyDefaultHandlerForURLScheme(scheme)
            default = ""
            if default_ptr:
                try:
                    default = self.string_value(default_ptr)
                finally:
                    self.cf.CFRelease(default_ptr)
            array_ptr = self.core.LSCopyAllHandlersForURLScheme(scheme)
            values: list[str] = []
            if array_ptr:
                try:
                    count = int(self.cf.CFArrayGetCount(array_ptr))
                    for index in range(max(0, count)):
                        item = self.cf.CFArrayGetValueAtIndex(array_ptr, index)
                        value = self.string_value(item) if item else ""
                        if value and value not in values:
                            values.append(value)
                finally:
                    self.cf.CFRelease(array_ptr)
        finally:
            self.cf.CFRelease(scheme)
        if default and default not in values:
            values.insert(0, default)
        elif default in values:
            values.remove(default)
            values.insert(0, default)
        return default, values

    def applications(self, bundle_id: str) -> list[Path]:
        bundle = self.string(bundle_id)
        error = ctypes.c_void_p()
        try:
            array_ptr = self.core.LSCopyApplicationURLsForBundleIdentifier(
                bundle, ctypes.byref(error)
            )
        finally:
            self.cf.CFRelease(bundle)
        if not array_ptr:
            return []
        paths: list[Path] = []
        try:
            count = int(self.cf.CFArrayGetCount(array_ptr))
            for index in range(max(0, count)):
                item = self.cf.CFArrayGetValueAtIndex(array_ptr, index)
                path = self.url_path(item) if item else None
                if path is not None and path.is_dir() and path not in paths:
                    paths.append(path)
        finally:
            self.cf.CFRelease(array_ptr)
        return paths


def _macos_applications(scheme: str) -> list[HostApplication]:
    launch_services = _MacLaunchServices()
    default_id, handler_ids = launch_services.handlers(scheme)
    result: list[HostApplication] = []
    for bundle_id in handler_ids:
        for application in launch_services.applications(bundle_id):
            try:
                executable, identity = _bundle_executable(application)
            except HostApplicationResolutionError:
                continue
            candidate = HostApplication(
                executable=executable,
                identity=identity,
                source="launch_services",
                is_default=(bundle_id == default_id),
            )
            if candidate not in result:
                result.append(candidate)
    return result


def _windows_prog_id_executable(prog_id: str) -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command"
        ) as key:
            command = str(winreg.QueryValueEx(key, None)[0]).strip()
    except (ImportError, OSError):
        return None
    tokens = shlex.split(os.path.expandvars(command), posix=False)
    if not tokens:
        return None
    raw = tokens[0].strip('"')
    executable = Path(raw)
    if not executable.is_absolute():
        resolved = shutil.which(raw)
        executable = Path(resolved) if resolved else executable
    return executable.resolve() if executable.is_file() else None


def _windows_default_prog_id(scheme: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProgId")[0]).strip()
    except (ImportError, OSError):
        return ""


def _windows_registered_prog_ids(scheme: str) -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    values: list[str] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        base = r"Software\Clients\StartMenuInternet"
        try:
            with winreg.OpenKey(hive, base) as root:
                count = int(winreg.QueryInfoKey(root)[0])
                clients = [winreg.EnumKey(root, index) for index in range(count)]
        except OSError:
            continue
        for client in clients:
            try:
                with winreg.OpenKey(
                    hive, rf"{base}\{client}\Capabilities\URLAssociations"
                ) as key:
                    prog_id = str(winreg.QueryValueEx(key, scheme)[0]).strip()
            except OSError:
                continue
            if prog_id and prog_id not in values:
                values.append(prog_id)
    return values


def _windows_applications(scheme: str) -> list[HostApplication]:
    default = _windows_default_prog_id(scheme)
    prog_ids = _windows_registered_prog_ids(scheme)
    if default and default not in prog_ids:
        prog_ids.insert(0, default)
    elif default in prog_ids:
        prog_ids.remove(default)
        prog_ids.insert(0, default)
    result: list[HostApplication] = []
    for prog_id in prog_ids:
        executable = _windows_prog_id_executable(prog_id)
        if executable is not None:
            result.append(HostApplication(
                executable=executable,
                identity=prog_id,
                source="windows_url_association",
                is_default=(prog_id == default),
            ))
    return result


def _xdg_data_roots() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
    data_dirs = [Path(item) for item in os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
    ).split(os.pathsep) if item]
    return [data_home, *data_dirs]


def _linux_default_desktop_id(scheme: str) -> str:
    xdg_mime = shutil.which("xdg-mime")
    if not xdg_mime:
        return ""
    completed = subprocess.run(
        [xdg_mime, "query", "default", f"x-scheme-handler/{scheme}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=5,
        check=False,
    )
    value = completed.stdout.strip() if completed.returncode == 0 else ""
    return value if value and "/" not in value and "\\" not in value else ""


def _linux_registered_desktop_ids(scheme: str) -> list[str]:
    gio = shutil.which("gio")
    if not gio:
        return []
    completed = subprocess.run(
        [gio, "mime", f"x-scheme-handler/{scheme}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=5,
        check=False,
    )
    if completed.returncode != 0:
        return []
    values: list[str] = []
    for line in completed.stdout.splitlines():
        if ":" not in line:
            continue
        prefix, tail = line.split(":", 1)
        if "application" not in prefix.lower():
            continue
        for value in tail.replace(",", ";").split(";"):
            desktop_id = value.strip()
            if desktop_id.endswith(".desktop") and desktop_id not in values:
                values.append(desktop_id)
    return values


def _desktop_entry_executable(desktop_id: str) -> Path | None:
    if not desktop_id or "/" in desktop_id or "\\" in desktop_id:
        return None
    desktop_file = next(
        (
            root / "applications" / desktop_id
            for root in _xdg_data_roots()
            if (root / "applications" / desktop_id).is_file()
        ),
        None,
    )
    if desktop_file is None:
        return None
    try:
        exec_line = next(
            line.split("=", 1)[1].strip()
            for line in desktop_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("Exec=")
        )
    except (OSError, StopIteration):
        return None
    tokens = shlex.split(exec_line)
    if not tokens:
        return None
    raw = os.path.expandvars(tokens[0])
    resolved = raw if os.path.isabs(raw) else shutil.which(raw)
    return Path(resolved).resolve() if resolved and Path(resolved).is_file() else None


def _linux_applications(scheme: str) -> list[HostApplication]:
    default = _linux_default_desktop_id(scheme)
    desktop_ids = _linux_registered_desktop_ids(scheme)
    if default and default not in desktop_ids:
        desktop_ids.insert(0, default)
    elif default in desktop_ids:
        desktop_ids.remove(default)
        desktop_ids.insert(0, default)
    result: list[HostApplication] = []
    for desktop_id in desktop_ids:
        executable = _desktop_entry_executable(desktop_id)
        if executable is not None:
            result.append(HostApplication(
                executable=executable,
                identity=desktop_id,
                source="xdg_url_handler",
                is_default=(desktop_id == default),
            ))
    return result


def resolve_url_scheme_applications(scheme: str) -> list[HostApplication]:
    normalized = str(scheme or "").strip().lower()
    compact = normalized.replace("+", "").replace("-", "").replace(".", "")
    if not normalized or not compact.isalnum():
        raise HostApplicationResolutionError("URL scheme 无效。")
    if sys.platform == "darwin":
        return _macos_applications(normalized)
    if os.name == "nt":
        return _windows_applications(normalized)
    return _linux_applications(normalized)


__all__ = [
    "HostApplication",
    "HostApplicationResolutionError",
    "resolve_url_scheme_applications",
]
