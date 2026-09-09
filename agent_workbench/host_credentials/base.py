from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class HostCredentialError(RuntimeError):
    """Credential broker failures that are safe to surface without secrets."""


@dataclass(frozen=True, slots=True)
class HostCredentialSession:
    session_id: str
    server_id: str
    service: str
    operation: str
    target_host: str
    root: Path
    askpass_path: Path
    expires_at: int

    def public_result(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "service": self.service,
            "operation": self.operation,
            "target_host": self.target_host,
            "read_root": str(self.root),
            "askpass_path": str(self.askpass_path),
            "expires_at": self.expires_at,
            "secret_exposed_to_runtime": False,
        }
