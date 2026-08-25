"""Agent Runtime - execution core for MicroMatrix Workbench."""

from __future__ import annotations

__all__ = ["__version__"]

# agent_runtime has its own semantic version lifecycle. It is intentionally
# independent from the desktop application's release tag and must be bumped
# when changes inside agent_runtime alter its MCP/runtime behaviour.
__version__ = "0.2.0"
