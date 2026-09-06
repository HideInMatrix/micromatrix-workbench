from __future__ import annotations

from typing import Any

from ...errors import ToolError


class ToolchainHandlers:
    """Use the same registration gate as command execution; no login-shell fallback."""

    def discover_toolchains(self, args: dict[str, Any]) -> dict[str, Any]:
        kinds = list(dict.fromkeys(str(k).strip().lower() for k in
                                   list(args.get("kinds") or ["node", "python", "go"])))
        primary = {"node": "node", "python": "python", "go": "go"}
        errors = {}
        self._verify_registered_toolchains()
        discovered = self.toolchains.discover(kinds)
        for kind in kinds:
            current = discovered["toolchains"].get(kind, {})
            if kind not in primary or current.get("selected") is not None:
                continue
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
            "shell_startup_files_evaluated": False,
            "home_scanned_recursively": False,
            "elevated_user_environment_queried": False,
            "missing": missing,
            "registration_errors": errors,
        }
