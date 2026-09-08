"""Persist successful checks independently of the WebView's ephemeral origin."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, fields
from pathlib import Path

from agent_runtime.atomic_io import atomic_write_json
from .release import ReleaseInfo, platform_asset_name

CHECK_INTERVAL_SECONDS = 24 * 60 * 60


class UpdateCheckCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, version: str, proxy: str, now: float) -> tuple[ReleaseInfo | None, float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema") != 1:
                return None, 0
            if data.get("proxy") != proxy or data.get("platform") != platform_asset_name():
                return None, 0
            raw = data.get("release")
            if not isinstance(raw, dict) or raw.get("current_version") != version:
                return None, 0
            for field in fields(ReleaseInfo):
                expected = bool if field.name == "update_available" else str
                if type(raw.get(field.name)) is not expected:
                    return None, 0
            checked = data.get("checked_at")
            if type(checked) not in (int, float) or not math.isfinite(checked) or not 0 < checked <= now:
                return None, 0
            return ReleaseInfo(**{field.name: raw[field.name] for field in fields(ReleaseInfo)}), checked
        except (OSError, ValueError, TypeError):
            # A missing/corrupt cache is a cache miss, never a startup failure.
            return None, 0

    def write(self, release: ReleaseInfo, proxy: str, checked_at: float) -> None:
        atomic_write_json(self.path, {
            "schema": 1, "proxy": proxy, "platform": platform_asset_name(),
            "checked_at": checked_at, "release": asdict(release),
        }, mode=0o600)
