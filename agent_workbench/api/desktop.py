from __future__ import annotations

from .toolchains import ToolchainAPI
from .approvals import ApprovalAPI
from .base import DesktopBaseAPI
from .services import ServiceAPI
from .update import UpdateAPI
from .workbench import WorkbenchAPI


class DesktopAPI(
    ToolchainAPI,
    ApprovalAPI,
    WorkbenchAPI,
    ServiceAPI,
    UpdateAPI,
    DesktopBaseAPI,
):
    """Composed pywebview JS ↔ Python facade."""


__all__ = ["DesktopAPI"]
