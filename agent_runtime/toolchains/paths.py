"""Platform defaults only. User manager directories are discovery candidates, not grants."""
from __future__ import annotations

import os
from pathlib import Path


def system_path_entries() -> list[str]:
    if os.name == "nt":
        root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        return [str(root / "System32"), str(root)]
    raw = ""
    try:
        raw = os.confstr("CS_PATH") or ""
    except (AttributeError, OSError, ValueError):
        pass
    raw = raw or os.defpath
    return list(dict.fromkeys(
        item for item in raw.split(os.pathsep)
        if item and Path(item).is_absolute()
    ))


def system_read_roots() -> list[Path]:
    import sys
    if sys.platform != "darwin":
        return []
    return [Path(value) for value in ("/System", "/Library", "/usr", "/bin", "/sbin",
                                      "/private/etc", "/private/var/db", "/private/var/select")]


