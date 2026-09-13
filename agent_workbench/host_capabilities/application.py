from __future__ import annotations

import hashlib
import plistlib
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import HostCapabilityDescriptor, HostCapabilityError


_REF_TTL_SECONDS = 300.0


def _md_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass(frozen=True, slots=True)
class _ApplicationTarget:
    name: str
    bundle_id: str
    version: str
    build: str
    path: Path
    executable: Path
    identity_fingerprint: str


class ApplicationHostCapability:
    """Resolve and control registered GUI applications in the Desktop Host.

    Runtime never scans host application directories or guesses installation
    paths.  Mutating actions consume a short-lived opaque application_ref that
    was produced by resolve/list, so the approved application identity cannot
    silently change between permission preflight and execution.
    """

    descriptor = HostCapabilityDescriptor(
        name="application",
        provider="os_application_registry",
        session_based=False,
        operations=("resolve", "list", "launch", "activate", "quit"),
    )

    def __init__(self, *, generation: str = "") -> None:
        self._generation = generation or "standalone"
        self._generation_prefix = self._generation[:10]
        self._references: dict[str, tuple[str, str, _ApplicationTarget, float]] = {}
        self._fingerprints: dict[tuple[str, int, int], str] = {}

    def _require_macos(self) -> None:
        if sys.platform != "darwin":
            raise HostCapabilityError(
                f"当前平台 {sys.platform} 尚未实现 GUI Application Lifecycle Host Driver。",
                code="APPLICATION_PLATFORM_UNSUPPORTED",
                stage="preflight",
            )

    @staticmethod
    def _tool(name: str) -> str:
        path = shutil.which(name)
        if not path:
            raise HostCapabilityError(
                f"宿主系统缺少应用生命周期所需能力: {name}",
                code="APPLICATION_RESOLVER_UNAVAILABLE",
                stage="application_resolution",
            )
        return path

    @staticmethod
    def _run(argv: list[str], *, code: str, stage: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HostCapabilityError(
                str(exc) or type(exc).__name__, code=code, stage=stage
            ) from exc

    def _binary_hash(self, executable: Path) -> str:
        try:
            stat = executable.stat()
        except OSError:
            return ""
        key = (str(executable), int(stat.st_size), int(stat.st_mtime_ns))
        cached = self._fingerprints.get(key)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        try:
            with executable.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return ""
        value = digest.hexdigest()
        self._fingerprints[key] = value
        return value

    def _target(self, path: Path) -> _ApplicationTarget | None:
        try:
            bundle = path.resolve(strict=True)
        except OSError:
            return None
        if bundle.suffix.casefold() != ".app":
            return None
        try:
            with (bundle / "Contents" / "Info.plist").open("rb") as stream:
                info = plistlib.load(stream)
        except (OSError, plistlib.InvalidFileException, ValueError):
            return None
        bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
        executable_name = str(info.get("CFBundleExecutable") or "").strip()
        executable = bundle / "Contents" / "MacOS" / executable_name
        if not bundle_id or not executable_name or not executable.is_file():
            return None
        binary_hash = self._binary_hash(executable)
        fingerprint = ""
        if binary_hash:
            material = "\0".join(
                (bundle_id, str(bundle), str(executable), binary_hash)
            ).encode("utf-8", "surrogateescape")
            fingerprint = hashlib.sha256(material).hexdigest()
        return _ApplicationTarget(
            name=str(
                info.get("CFBundleDisplayName")
                or info.get("CFBundleName")
                or bundle.stem
            ).strip(),
            bundle_id=bundle_id,
            version=str(info.get("CFBundleShortVersionString") or ""),
            build=str(info.get("CFBundleVersion") or ""),
            path=bundle,
            executable=executable,
            identity_fingerprint=fingerprint,
        )

    def _search(self, expression: str, *, max_results: int) -> list[_ApplicationTarget]:
        self._require_macos()
        completed = self._run(
            [self._tool("mdfind"), expression],
            code="APPLICATION_RESOLUTION_FAILED",
            stage="application_resolution",
        )
        if completed.returncode != 0:
            raise HostCapabilityError(
                completed.stderr.strip() or "macOS application metadata query failed.",
                code="APPLICATION_RESOLUTION_FAILED",
                stage="application_resolution",
            )
        values: list[_ApplicationTarget] = []
        seen: set[str] = set()
        for raw in completed.stdout.splitlines():
            target = self._target(Path(raw.strip()))
            if target is None or target.bundle_id in seen:
                continue
            values.append(target)
            seen.add(target.bundle_id)
            if len(values) >= max_results:
                break
        return values

    def _resolve(self, name: str, bundle_id: str) -> _ApplicationTarget:
        app_name = name.strip()
        app_bundle_id = bundle_id.strip()
        if not app_name and not app_bundle_id:
            raise HostCapabilityError(
                "application.resolve 需要 name 或 bundle_id。",
                code="APPLICATION_ARGUMENT_INVALID",
                stage="validation",
            )
        if app_bundle_id:
            expression = f'kMDItemCFBundleIdentifier == "{_md_query_value(app_bundle_id)}"'
        else:
            value = _md_query_value(app_name)
            expression = (
                f'(kMDItemDisplayName == "{value}"cd || '
                f'kMDItemFSName == "{value}.app"cd) && '
                'kMDItemContentType == "com.apple.application-bundle"'
            )
        candidates = self._search(expression, max_results=16)
        if not candidates:
            raise HostCapabilityError(
                f"当前用户应用注册表中找不到应用: {app_bundle_id or app_name}",
                code="APPLICATION_NOT_FOUND",
                stage="application_resolution",
            )
        exact = next(
            (
                item for item in candidates
                if (app_bundle_id and item.bundle_id == app_bundle_id)
                or (app_name and item.name.casefold() == app_name.casefold())
            ),
            candidates[0],
        )
        return exact

    def _cleanup_refs(self) -> None:
        now = time.monotonic()
        for ref, record in tuple(self._references.items()):
            if record[3] <= now:
                self._references.pop(ref, None)

    def _remember(self, server_id: str, principal_hash: str, target: _ApplicationTarget) -> str:
        self._cleanup_refs()
        for ref, record in tuple(self._references.items()):
            owner_server, owner_principal, current, _deadline = record
            if (
                owner_server == server_id
                and owner_principal == principal_hash
                and current.bundle_id == target.bundle_id
                and current.identity_fingerprint == target.identity_fingerprint
            ):
                self._references[ref] = (
                    server_id, principal_hash, target, time.monotonic() + _REF_TTL_SECONDS
                )
                return ref
        ref = f"app_{self._generation_prefix}_{secrets.token_urlsafe(12)}"
        self._references[ref] = (
            server_id, principal_hash, target, time.monotonic() + _REF_TTL_SECONDS
        )
        return ref

    def _from_ref(self, server_id: str, principal_hash: str, ref: str) -> _ApplicationTarget:
        self._cleanup_refs()
        record = self._references.get(ref)
        if record is None or record[0] != server_id or record[1] != principal_hash:
            raise HostCapabilityError(
                "application_ref 已过期或不属于当前客户端/Profile；请重新 resolve。",
                code="APPLICATION_REF_EXPIRED",
                stage="application_resolution",
            )
        target = record[2]
        current = self._target(target.path)
        if (
            current is None
            or current.bundle_id != target.bundle_id
            or not target.identity_fingerprint
            or current.identity_fingerprint != target.identity_fingerprint
        ):
            self._references.pop(ref, None)
            raise HostCapabilityError(
                "应用身份在 resolve 后发生变化；旧 application_ref 已失效，请重新 resolve 并授权。",
                code="APPLICATION_IDENTITY_CHANGED",
                stage="application_resolution",
            )
        self._references[ref] = (
            server_id, principal_hash, current, time.monotonic() + _REF_TTL_SECONDS
        )
        return current

    @staticmethod
    def _public(ref: str, target: _ApplicationTarget) -> dict[str, Any]:
        return {
            "application_ref": ref,
            "application": {
                "name": target.name,
                "id": target.bundle_id,
                "version": target.version,
                "build": target.build,
                "identity_fingerprint": target.identity_fingerprint or None,
            },
        }

    def _open(self, target: _ApplicationTarget, *, new_instance: bool = False) -> None:
        argv = [self._tool("open")]
        if new_instance:
            argv.append("-n")
        argv.append(str(target.path))
        completed = self._run(argv, code="APPLICATION_LAUNCH_FAILED", stage="application_launch")
        if completed.returncode != 0:
            raise HostCapabilityError(
                completed.stderr.strip() or f"无法启动应用: {target.name}",
                code="APPLICATION_LAUNCH_FAILED",
                stage="application_launch",
            )

    def _activate(self, target: _ApplicationTarget) -> None:
        """Bring an already-running macOS application to the foreground.

        ``open <bundle>`` is reliable for launching applications, but macOS is
        allowed to leave an already-running application in the background.  A
        Desktop control caller needs a deterministic foreground transition
        without introducing Apple Events/Automation permission, so prefer the
        native NSRunningApplication activation API and fall back to ``open``
        only when the application is not currently running or AppKit is not
        available.
        """
        try:
            from AppKit import (
                NSApplicationActivateAllWindows,
                NSApplicationActivateIgnoringOtherApps,
                NSRunningApplication,
            )

            options = (
                NSApplicationActivateAllWindows
                | NSApplicationActivateIgnoringOtherApps
            )
            applications = NSRunningApplication.runningApplicationsWithBundleIdentifier_(
                target.bundle_id
            )
            for application in applications or ():
                if bool(application.activateWithOptions_(options)):
                    return
        except Exception:
            pass
        self._open(target)

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del session_id
        principal_hash = str(parameters.pop("_principal_hash", "") or "").strip()
        if not principal_hash:
            raise HostCapabilityError(
                "Application Host 请求缺少已认证 principal 绑定。",
                code="APPLICATION_PRINCIPAL_REQUIRED",
                stage="authorization",
            )
        preflight = bool(parameters.pop("_preflight", False))
        if action == "resolve":
            target = self._resolve(
                str(parameters.get("name") or ""), str(parameters.get("bundle_id") or "")
            )
            return {
                **self._public(self._remember(server_id, principal_hash, target), target),
                "resolver": "macos_spotlight_registry",
                "generation": self._generation,
            }
        if action == "list":
            query = str(parameters.get("query") or "").strip()
            limit = max(1, min(int(parameters.get("max_results", 30)), 100))
            value = _md_query_value(query)
            expression = (
                f'(kMDItemDisplayName == "*{value}*"cd || '
                f'kMDItemFSName == "*{value}*.app"cd || '
                f'kMDItemCFBundleIdentifier == "*{value}*"cd) && '
                'kMDItemContentType == "com.apple.application-bundle"'
                if query
                else 'kMDItemContentType == "com.apple.application-bundle"'
            )
            values = self._search(expression, max_results=limit)
            return {
                "applications": [
                    self._public(self._remember(server_id, principal_hash, item), item)
                    for item in values
                ],
                "count": len(values),
                "truncated": len(values) >= limit,
                "resolver": "macos_spotlight_registry",
                "generation": self._generation,
            }
        ref = str(parameters.get("application_ref") or "").strip()
        target = self._from_ref(server_id, principal_hash, ref)
        if preflight:
            return {
                "preflight": True,
                **self._public(ref, target),
            }
        if action == "launch":
            self._open(target, new_instance=bool(parameters.get("new_instance", False)))
            return {**self._public(ref, target), "launched": True}
        if action == "activate":
            self._activate(target)
            return {**self._public(ref, target), "activated": True}
        if action == "quit":
            osascript = self._tool("osascript")
            escaped = target.bundle_id.replace("\\", "\\\\").replace('"', '\\"')
            completed = self._run(
                [osascript, "-e", f'tell application id "{escaped}" to quit'],
                code="APPLICATION_QUIT_FAILED",
                stage="application_control",
            )
            if completed.returncode != 0:
                raise HostCapabilityError(
                    completed.stderr.strip() or f"无法退出应用: {target.name}",
                    code="APPLICATION_QUIT_FAILED",
                    stage="application_control",
                )
            return {**self._public(ref, target), "quit_requested": True}
        raise HostCapabilityError(
            f"application 不支持 action: {action}",
            code="APPLICATION_ACTION_UNSUPPORTED",
            stage="validation",
        )

    def close_server(self, server_id: str) -> None:
        for ref, record in tuple(self._references.items()):
            if record[0] == server_id:
                self._references.pop(ref, None)

    def close(self) -> None:
        self._references.clear()


__all__ = ["ApplicationHostCapability"]
