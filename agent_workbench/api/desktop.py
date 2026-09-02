from __future__ import annotations

from .approvals import ApprovalAPI
from .base import DesktopBaseAPI
from .oauth import OAuthAPI
from .services import ServiceAPI
from .update import UpdateAPI
from .workbench import WorkbenchAPI


class DesktopAPI(
    ApprovalAPI,
    WorkbenchAPI,
    ServiceAPI,
    OAuthAPI,
    UpdateAPI,
    DesktopBaseAPI,
):
    """Composed pywebview JS ↔ Python facade."""


__all__ = ["DesktopAPI"]
