"""Release discovery and in-app update services."""

from .installer import current_install_target
from .manager import UpdateManager, UpdateStatus
from .release import (
    DEFAULT_GITHUB_DOWNLOAD_PROXY,
    ReleaseInfo,
    apply_download_proxy,
    fetch_latest_release,
    is_newer_version,
    normalize_download_proxy_prefix,
    platform_asset_name,
    updater_asset_name,
)

__all__ = [
    "DEFAULT_GITHUB_DOWNLOAD_PROXY",
    "ReleaseInfo",
    "UpdateManager",
    "UpdateStatus",
    "apply_download_proxy",
    "current_install_target",
    "fetch_latest_release",
    "is_newer_version",
    "normalize_download_proxy_prefix",
    "platform_asset_name",
    "updater_asset_name",
]
