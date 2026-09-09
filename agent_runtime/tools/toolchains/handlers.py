from __future__ import annotations

import os
from typing import Any

from ...errors import ToolError


class ToolchainHandlers:
    """Use the same desktop Host-resolution and registration gate as execution."""

    def discover_toolchains(self, args: dict[str, Any]) -> dict[str, Any]:
        kinds = list(dict.fromkeys(str(k).strip().lower() for k in
                                   list(args.get("kinds") or ["node", "python", "go"])))
        primary = {"node": "node", "python": "python", "go": "go"}
        errors = {}
        host_resolution_attempted = False
        self._verify_registered_toolchains()
        discovered = self.toolchains.discover(kinds)
        for kind in kinds:
            current = discovered["toolchains"].get(kind, {})
            if kind not in primary or current.get("selected") is not None:
                continue
            host_resolution_attempted = True
            try:
                self._resolve_program(primary[kind])
            except ToolError as exc:
                errors[kind] = exc.payload()
        # Registration may have replaced the resolver, so never return the old snapshot.
        discovered = self.toolchains.discover(kinds)
        missing = [kind for kind in kinds
                   if not discovered["toolchains"].get(kind, {}).get("selected")]
        return {
            **discovered,
            "shell_startup_files_evaluated": host_resolution_attempted and os.name != "nt",
            "home_scanned_recursively": False,
            "elevated_user_environment_queried": False,
            "host_resolution": "desktop_command",
            "host_user_environment_queried": host_resolution_attempted,
            "host_environment_exposed_to_ai": False,
            "missing": missing,
            "registration_errors": errors,
        }
