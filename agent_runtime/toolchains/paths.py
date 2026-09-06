"""Platform defaults only. User manager directories are discovery candidates, not grants."""
from __future__ import annotations

import os
import platform
from pathlib import Path


def system_path_entries() -> list[str]:
    if os.name == "nt":
        root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        return [str(root / "System32"), str(root)]
    if platform.system().lower() == "darwin":
        return ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return ["/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin", "/sbin"]


def system_read_roots() -> list[Path]:
    import sys
    if sys.platform != "darwin":
        return []
    return [Path(value) for value in ("/System", "/Library", "/usr", "/bin", "/sbin",
                                      "/private/etc", "/private/var/db", "/private/var/select",
                                      "/opt/homebrew", "/usr/local")]


