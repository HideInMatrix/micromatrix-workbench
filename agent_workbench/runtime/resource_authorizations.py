from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_json

from ..core.settings import settings_dir


class ResourceAuthorizationStore:
    """Persistent grants for a verified resource exposed by any capability.

    The permission broker owns persistence. Individual tools only provide a
    trusted resource identity in their preflight context; they do not implement
    their own authorization database or matching rules.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings_dir() / "resource-authorizations.json")
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
    def _trusted_resource(request: dict[str, Any]) -> dict[str, str] | None:
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            return None
        trusted = arguments.get("_trusted_context")
        if not isinstance(trusted, dict):
            return None
        resource = trusted.get("authorization_resource")
        if not isinstance(resource, dict):
            return None
        if resource.get("persistent_authorization_supported") is not True:
            return None
        resource_type = str(resource.get("type") or "").strip()
        resource_id = str(resource.get("id") or "").strip()
        fingerprint = str(resource.get("identity_fingerprint") or "").strip()
        if not resource_type or not resource_id or not fingerprint:
            return None
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_name": str(resource.get("name") or resource_id)[:300],
            "identity_fingerprint": fingerprint,
        }

    @classmethod
    def persistent_context(cls, request: dict[str, Any]) -> dict[str, str] | None:
        resource = cls._trusted_resource(request)
        if resource is None:
            return None
        server_id = str(request.get("server_id") or "").strip()
        principal_hash = str(request.get("principal_hash") or "").strip()
        tool_name = str(request.get("tool_name") or "").strip()
        permission = str(request.get("permission") or "").strip()
        if not server_id or not principal_hash or not tool_name or not permission:
            return None
        return {
            "server_id": server_id,
            "principal_hash": principal_hash,
            "tool_name": tool_name,
            "permission": permission,
            **resource,
        }

    def remember(self, request: dict[str, Any]) -> dict[str, Any] | None:
        context = self.persistent_context(request)
        if context is None:
            return None
        now = int(time.time())
        match_keys = (
            "server_id",
            "principal_hash",
            "tool_name",
            "permission",
            "resource_type",
            "resource_id",
            "identity_fingerprint",
        )
        with self._lock:
            values = self._load()
            existing = next(
                (
                    item
                    for item in values
                    if all(item.get(key) == context[key] for key in match_keys)
                ),
                None,
            )
            if existing is None:
                existing = {
                    "id": f"rar_{secrets.token_urlsafe(14)}",
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
        match_keys = (
            "server_id",
            "principal_hash",
            "tool_name",
            "permission",
            "resource_type",
            "resource_id",
            "identity_fingerprint",
        )
        with self._lock:
            values = self._load()
            for item in values:
                if all(item.get(key) == context[key] for key in match_keys):
                    item["last_used_at"] = int(time.time())
                    self._save(values)
                    return dict(item)
        return None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            values = self._load()
        return [
            {
                "id": str(item.get("id") or ""),
                "server_id": str(item.get("server_id") or ""),
                "tool_name": str(item.get("tool_name") or ""),
                "permission": str(item.get("permission") or ""),
                "resource_type": str(item.get("resource_type") or ""),
                "resource_id": str(item.get("resource_id") or ""),
                "resource_name": str(item.get("resource_name") or ""),
                "identity_fingerprint": str(item.get("identity_fingerprint") or ""),
                "created_at": int(item.get("created_at") or 0),
                "last_used_at": int(item.get("last_used_at") or 0),
            }
            for item in values
        ]

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


__all__ = ["ResourceAuthorizationStore"]
