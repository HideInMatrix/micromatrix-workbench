from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from agent_workbench.host_execution import HostProcessSupervisor

from .application import ApplicationHostCapability
from .artifact import HostArtifactCapability
from .base import HostCapabilityError, HostCapabilityProvider
from .browser import BrowserHostCapability
from .desktop import DesktopHostCapability


class HostCapabilityManager:
    """Desktop-hosted capabilities that must never execute in Runtime sandbox."""

    def __init__(
        self,
        execution_root: Path,
        *,
        generation: str = "",
        providers: Iterable[HostCapabilityProvider] | None = None,
    ) -> None:
        self._processes = HostProcessSupervisor(
            execution_root,
            generation=generation or "standalone",
        )
        values = (
            tuple(providers)
            if providers is not None
            else (
                BrowserHostCapability(self._processes, generation=generation),
                DesktopHostCapability(generation=generation),
                ApplicationHostCapability(generation=generation),
                HostArtifactCapability(),
            )
        )
        self._providers = {provider.descriptor.name: provider for provider in values}

    def catalog(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for provider in self._providers.values():
            try:
                values.append(provider.descriptor.to_dict())
            except Exception as exc:
                values.append(
                    {
                        "name": getattr(getattr(provider, "descriptor", None), "name", "unknown"),
                        "provider": type(provider).__name__,
                        "session_based": False,
                        "operations": [],
                        "status": "degraded",
                        "error": type(exc).__name__,
                    }
                )
        return values

    def invoke(
        self,
        capability: str,
        action: str,
        *,
        server_id: str,
        session_id: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = self._providers.get(capability)
        if provider is None:
            raise HostCapabilityError(f"Workbench Host 不支持 Capability: {capability}")
        if action not in provider.descriptor.operations:
            raise HostCapabilityError(f"Capability {capability} 不支持 action: {action}")
        return provider.invoke(
            action,
            server_id=server_id,
            session_id=session_id,
            parameters=dict(parameters or {}),
        )

    def close_server(self, server_id: str) -> None:
        for provider in self._providers.values():
            provider.close_server(server_id)
        self._processes.close_server(server_id)

    def stop_desktop_input(self, server_id: str) -> dict[str, Any]:
        provider = self._providers.get("desktop")
        stop = getattr(provider, "stop_server_input", None) if provider is not None else None
        if not callable(stop):
            raise HostCapabilityError("Desktop Provider 不支持本地停止输入。")
        result = stop(server_id)
        return dict(result) if isinstance(result, dict) else {
            "stopped": True,
            "server_id": server_id,
        }

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()
        self._processes.close()
