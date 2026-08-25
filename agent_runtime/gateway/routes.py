"""Path ownership resolution for Local MCP Gateway profiles."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .models import GatewayProfile


AUTHORIZATION_METADATA_PREFIX = "/.well-known/oauth-authorization-server"
PROTECTED_RESOURCE_METADATA_PREFIX = "/.well-known/oauth-protected-resource"
OPENID_CONFIGURATION_PREFIX = "/.well-known/openid-configuration"


@dataclass(frozen=True, slots=True)
class GatewayRoute:
    profile: GatewayProfile
    kind: str
    path: str


def request_path(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def request_host(value: str) -> str:
    raw = str(value or "").split(",", 1)[0].strip().lower()
    if not raw:
        return ""
    try:
        return (urlsplit(f"//{raw}").hostname or "").lower()
    except ValueError:
        return raw


def profile_host(profile: GatewayProfile) -> str:
    if not profile.public_url:
        return ""
    return (urlsplit(profile.public_url).hostname or "").lower()


class GatewayRouteResolver:
    """Resolve external MCP/OAuth paths to one registered profile.

    Direct profile routes use the instance path prefix. OAuth well-known
    metadata inserts the instance path after the RFC-defined prefix, so those
    routes are resolved separately.
    """

    def __init__(self, profiles: tuple[GatewayProfile, ...]) -> None:
        self._profiles = tuple(
            sorted(
                profiles,
                key=lambda profile: len(profile.instance_path),
                reverse=True,
            )
        )

    @staticmethod
    def _host_route(profile: GatewayProfile, path: str) -> GatewayRoute:
        if path.startswith(AUTHORIZATION_METADATA_PREFIX):
            kind = "oauth_authorization_metadata"
        elif path.startswith(OPENID_CONFIGURATION_PREFIX):
            kind = "oauth_authorization_metadata"
        elif path.startswith(PROTECTED_RESOURCE_METADATA_PREFIX):
            kind = "oauth_protected_resource_metadata"
        else:
            kind = "profile"
        return GatewayRoute(profile, kind, path)

    def resolve(self, value: str, host: str = "") -> GatewayRoute | None:
        path = request_path(value).rstrip("/") or "/"
        host_key = request_host(host)
        if host_key:
            for profile in self._profiles:
                if profile_host(profile) == host_key:
                    return self._host_route(profile, path)
            if host_key not in {"localhost", "127.0.0.1", "::1"}:
                return None
        for profile in self._profiles:
            instance = profile.instance_path
            authorization = AUTHORIZATION_METADATA_PREFIX + instance
            if path == authorization or path.startswith(authorization + "/"):
                return GatewayRoute(profile, "oauth_authorization_metadata", path)

            openid = OPENID_CONFIGURATION_PREFIX + instance
            if path == openid or path.startswith(openid + "/"):
                return GatewayRoute(profile, "oauth_authorization_metadata", path)

            profile_openid = instance + OPENID_CONFIGURATION_PREFIX
            if path == profile_openid or path.startswith(profile_openid + "/"):
                return GatewayRoute(profile, "oauth_authorization_metadata", path)

            protected = PROTECTED_RESOURCE_METADATA_PREFIX + instance
            if path == protected or path.startswith(protected + "/"):
                return GatewayRoute(profile, "oauth_protected_resource_metadata", path)

            if path == instance or path.startswith(instance + "/"):
                return GatewayRoute(profile, "profile", path)
        return None

