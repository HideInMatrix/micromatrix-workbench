"""In-memory permission grants scoped to one Runtime session."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from .capabilities import ELICITABLE_PERMISSIONS, SESSION_GRANTABLE_PERMISSIONS
from .state import arguments_digest


class PermissionGrantStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._grants: dict[str, dict[str, Any]] = {}
        self._session_principals: set[str] = set()
        # Resource-session grants are intentionally independent from the MCP
        # tool that requested them. One logical resource (for example one
        # Browser or Desktop Host session) may be operated by multiple public
        # tools, so tool_name must never become part of its authorization
        # identity.
        self._resource_session_permissions: dict[
            tuple[str, str, str], set[str]
        ] = {}

    def store(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        permission: str,
        principal: str,
        scope: str,
        ttl_seconds: int,
    ) -> tuple[str, int]:
        now = int(time.time())
        expires_at = now + max(1, min(int(ttl_seconds), 3_600))
        grant_id = f"ctg_{secrets.token_urlsafe(18)}"
        record = {
            "tool_name": tool_name,
            "arguments_hash": arguments_digest(tool_name, arguments),
            "permission": permission,
            "principal": principal or "anonymous",
            "scope": "session" if scope == "session" else "once",
            "expires_at": expires_at,
        }
        with self._lock:
            self._grants[grant_id] = record
        return grant_id, expires_at

    def permissions_for_call(
        self,
        name: str,
        arguments: dict[str, Any],
        principal: str,
    ) -> frozenset[str]:
        now = int(time.time())
        normalized_principal = principal or "anonymous"
        digest = arguments_digest(name, arguments)
        granted: set[str] = set()
        consume: list[str] = []
        with self._lock:
            for grant_id, record in list(self._grants.items()):
                if int(record.get("expires_at", 0)) < now:
                    self._grants.pop(grant_id, None)
                    continue
                if (
                    record.get("tool_name") != name
                    or record.get("arguments_hash") != digest
                    or record.get("principal") != normalized_principal
                ):
                    continue
                permission = record.get("permission")
                if isinstance(permission, str) and permission in ELICITABLE_PERMISSIONS:
                    granted.add(permission)
                    if record.get("scope") == "once":
                        consume.append(grant_id)
            for grant_id in consume:
                self._grants.pop(grant_id, None)
        return frozenset(granted)

    def session_permissions(self, principal: str) -> frozenset[str]:
        with self._lock:
            if (principal or "anonymous") in self._session_principals:
                return SESSION_GRANTABLE_PERMISSIONS
        return frozenset()

    def grant_session(self, principal: str) -> None:
        with self._lock:
            self._session_principals.add(principal or "anonymous")

    def grant_resource_session(
        self,
        principal: str,
        resource_type: str,
        resource_id: str,
        permission: str,
    ) -> None:
        normalized_principal = principal or "anonymous"
        normalized_type = str(resource_type or "").strip()
        normalized_id = str(resource_id or "").strip()
        if not normalized_type or not normalized_id or permission not in ELICITABLE_PERMISSIONS:
            return
        with self._lock:
            key = (normalized_principal, normalized_type, normalized_id)
            self._resource_session_permissions.setdefault(key, set()).add(permission)

    def resource_session_permissions(
        self,
        principal: str,
        resource_type: str,
        resource_id: str,
    ) -> frozenset[str]:
        normalized_type = str(resource_type or "").strip()
        normalized_id = str(resource_id or "").strip()
        if not normalized_type or not normalized_id:
            return frozenset()
        with self._lock:
            return frozenset(
                self._resource_session_permissions.get(
                    (principal or "anonymous", normalized_type, normalized_id),
                    set(),
                )
            )

    def revoke_resource_session(
        self,
        principal: str,
        resource_type: str,
        resource_id: str,
    ) -> None:
        with self._lock:
            self._resource_session_permissions.pop(
                (
                    principal or "anonymous",
                    str(resource_type or "").strip(),
                    str(resource_id or "").strip(),
                ),
                None,
            )

