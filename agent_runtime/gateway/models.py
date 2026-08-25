"""Local MCP Gateway profile models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..permissions.capabilities import PERMISSION_MODES


def normalize_instance_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    segments = [segment for segment in raw.strip("/").split("/") if segment]
    if not segments:
        return ""
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("gateway instance_path cannot contain dot segments")
    if segments[0] == ".well-known":
        raise ValueError("gateway instance_path cannot use the reserved .well-known prefix")
    return "/" + "/".join(segments)


def normalize_public_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("gateway public_url must be a complete http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("gateway public_url must not contain user info")
    if (parsed.path or "").rstrip("/") or parsed.query or parsed.fragment:
        raise ValueError("gateway public_url must contain only scheme and hostname")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), "", "", ""))


@dataclass(frozen=True, slots=True)
class GatewayProfile:
    profile_id: str
    instance_path: str
    workspace: Path
    public_url: str = ""
    permission_mode: str = "safe"
    allow_network: bool = False
    enable_view_image: bool = True

    def validated(self) -> "GatewayProfile":
        profile_id = self.profile_id.strip()
        if not profile_id:
            raise ValueError("gateway profile_id is required")
        permission_mode = self.permission_mode.strip().lower() or "safe"
        if permission_mode not in PERMISSION_MODES:
            raise ValueError(f"unknown gateway permission mode: {permission_mode}")
        return GatewayProfile(
            profile_id=profile_id,
            instance_path=normalize_instance_path(self.instance_path),
            workspace=self.workspace.expanduser(),
            public_url=normalize_public_url(self.public_url),
            permission_mode=permission_mode,
            allow_network=bool(self.allow_network),
            enable_view_image=bool(self.enable_view_image),
        )

