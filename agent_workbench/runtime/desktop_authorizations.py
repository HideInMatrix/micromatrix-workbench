from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_json

from ..core.settings import settings_dir


_PERMISSIONS = frozenset({"desktop_observe", "desktop_control"})


class DesktopAuthorizationStore:
    """Persistent Workbench approvals for trusted desktop application identities.

    Rules intentionally do not contain window ids, coordinates or observations.
    Those identities remain ephemeral and are re-established for every desktop
    session.  A rule only answers whether the same authenticated principal in
    the same Workbench profile may request the same capability for the same
    verified application identity without another Workbench approval prompt.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings_dir() / "desktop-authorizations.json")
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return []
        values = raw.get("rules")
        return [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []

    def _save(self, values: list[dict[str, Any]]) -> None:
        atomic_write_json(
            self.path,
            {"version": 1, "rules": values},
            mode=0o600,
        )

    @staticmethod
    def _trusted_application(request: dict[str, Any]) -> dict[str, Any] | None:
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            return None
        trusted = arguments.get("_trusted_context")
        if not isinstance(trusted, dict):
            return None
        target = trusted.get("target")
        if not isinstance(target, dict):
            return None
        application = target.get("application")
        if not isinstance(application, dict):
            return None
        application_id = str(application.get("id") or "").strip()
        fingerprint = str(application.get("identity_fingerprint") or "").strip()
        if not application_id or not fingerprint:
            return None
        if application.get("persistent_authorization_supported") is not True:
            return None
        return {
            "application_id": application_id,
            "identity_fingerprint": fingerprint,
            "application_name": str(application.get("name") or application_id)[:300],
        }

    @classmethod
    def persistent_context(cls, request: dict[str, Any]) -> dict[str, str] | None:
        if str(request.get("tool_name") or "") != "desktop":
            return None
        permission = str(request.get("permission") or "")
        if permission not in _PERMISSIONS:
            return None
        application = cls._trusted_application(request)
        if application is None:
            return None
        server_id = str(request.get("server_id") or "").strip()
        principal_hash = str(request.get("principal_hash") or "").strip()
        if not server_id or not principal_hash:
            return None
        return {
            "server_id": server_id,
            "principal_hash": principal_hash,
            "permission": permission,
            **application,
        }

    def remember(self, request: dict[str, Any]) -> dict[str, Any] | None:
        context = self.persistent_context(request)
        if context is None:
            return None
        now = int(time.time())
        with self._lock:
            values = self._load()
            existing = next(
                (
                    item
                    for item in values
                    if all(item.get(key) == context[key] for key in (
                        "server_id",
                        "principal_hash",
                        "permission",
                        "application_id",
                        "identity_fingerprint",
                    ))
                ),
                None,
            )
            if existing is None:
                existing = {
                    "id": f"dar_{secrets.token_urlsafe(14)}",
                    **context,
                    "created_at": now,
                    "last_used_at": now,
                }
                values.append(existing)
            else:
                existing.update(context)
                existing["last_used_at"] = now
            self._save(values)
            return dict(existing)

    def match(self, request: dict[str, Any]) -> dict[str, Any] | None:
        context = self.persistent_context(request)
        if context is None:
            return None
        with self._lock:
            values = self._load()
            for item in values:
                if all(item.get(key) == context[key] for key in (
                    "server_id",
                    "principal_hash",
                    "permission",
                    "application_id",
                    "identity_fingerprint",
                )):
                    item["last_used_at"] = int(time.time())
                    self._save(values)
                    return dict(item)
        return None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            values = self._load()
        public: list[dict[str, Any]] = []
        for item in values:
            public.append(
                {
                    "id": str(item.get("id") or ""),
                    "server_id": str(item.get("server_id") or ""),
                    "permission": str(item.get("permission") or ""),
                    "application_id": str(item.get("application_id") or ""),
                    "application_name": str(item.get("application_name") or ""),
                    "identity_fingerprint": str(item.get("identity_fingerprint") or ""),
                    "created_at": int(item.get("created_at") or 0),
                    "last_used_at": int(item.get("last_used_at") or 0),
                }
            )
        return public

    def revoke(self, rule_id: str) -> bool:
        normalized = str(rule_id or "").strip()
        if not normalized:
            return False
        with self._lock:
            values = self._load()
            filtered = [item for item in values if str(item.get("id") or "") != normalized]
            if len(filtered) == len(values):
                return False
            self._save(filtered)
            return True


__all__ = ["DesktopAuthorizationStore"]
