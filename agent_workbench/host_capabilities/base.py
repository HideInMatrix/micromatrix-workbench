from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class HostCapabilityError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "HOST_CAPABILITY_FAILED",
        stage: str = "provider",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


@dataclass(frozen=True, slots=True)
class HostCapabilityDescriptor:
    name: str
    provider: str
    session_based: bool
    operations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "session_based": self.session_based,
            "operations": list(self.operations),
        }


class HostCapabilityProvider(Protocol):
    descriptor: HostCapabilityDescriptor

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]: ...

    def close_server(self, server_id: str) -> None: ...

    def close(self) -> None: ...
