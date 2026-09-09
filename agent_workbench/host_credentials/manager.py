from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .base import HostCredentialError, HostCredentialSession
from .git_https import prepare_git_https_session


class HostCredentialManager:
    """Desktop-only credentials kept out of Runtime tool results and logs."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._sessions: dict[str, HostCredentialSession] = {}
        self._lock = threading.RLock()

    def prepare(
        self,
        service: str,
        operation: str,
        *,
        server_id: str,
        target_url: str,
        workspace: str,
        ttl_seconds: int = 120,
    ) -> dict[str, Any]:
        self.cleanup_expired()
        if service != "git_https":
            raise HostCredentialError(f"Workbench Host 不支持 Credential service: {service}")
        session, helper = prepare_git_https_session(
            broker_root=self.root,
            server_id=server_id,
            operation=operation,
            target_url=target_url,
            workspace=workspace,
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return {**session.public_result(), "helper": helper}

    def release(self, server_id: str, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.server_id != server_id:
                return False
            self._sessions.pop(session_id, None)
        shutil.rmtree(session.root, ignore_errors=True)
        return True

    def cleanup_expired(self) -> None:
        now = int(time.time())
        with self._lock:
            expired = [item for item in self._sessions.values() if item.expires_at <= now]
        for session in expired:
            self.release(session.server_id, session.session_id)

    def close_server(self, server_id: str) -> None:
        with self._lock:
            sessions = [item for item in self._sessions.values() if item.server_id == server_id]
        for session in sessions:
            self.release(server_id, session.session_id)

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self.release(session.server_id, session.session_id)
        shutil.rmtree(self.root, ignore_errors=True)


__all__ = ["HostCredentialError", "HostCredentialManager"]
