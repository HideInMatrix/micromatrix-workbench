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
        host_shell_resolution_attempted = False
        self._verify_registered_toolchains()
        discovered = self.toolchains.discover(kinds)
        for kind in kinds:
            current = discovered["toolchains"].get(kind, {})
            if kind not in primary:
                continue
            project_context = self.toolchains.project_context(
                primary[kind], self.workspace.root
            )
            requirements = project_context.get("requirements")
            has_python_venv = (
                kind == "python"
                and isinstance(requirements, list)
                and any(
                    isinstance(item, dict)
                    and item.get("type") == "python_virtual_environment"
                    for item in requirements
                )
            )
            has_node_project_context = (
                kind == "node"
                and isinstance(requirements, list)
                and any(
                    isinstance(item, dict)
                    and item.get("type") in {
                        "runtime_version",
                        "node_engine",
                        "package_manager",
                    }
                    for item in requirements
                )
            )
            selected = current.get("selected") if isinstance(current, dict) else None
            selected_source = (
                str(selected.get("source") or "")
                if isinstance(selected, dict)
                else ""
            )
            needs_project_registration = (
                (has_python_venv or has_node_project_context)
                and selected_source != "registered"
            )
            if selected is not None and not needs_project_registration:
                continue
            try:
                if has_python_venv or has_node_project_context:
                    if has_node_project_context:
                        host_shell_resolution_attempted = True
                    resolution_cwd = self.workspace.root
                    if has_node_project_context:
                        context_cwd = str(project_context.get("cwd") or ".")
                        candidate_cwd = (self.workspace.root / context_cwd).resolve()
                        try:
                            candidate_cwd.relative_to(self.workspace.root)
                        except ValueError:
                            pass
                        else:
                            if candidate_cwd.is_dir():
                                resolution_cwd = candidate_cwd
                    proposal = self._resolve_host_tool_proposal(
                        primary[kind], cwd=resolution_cwd
                    )
                    self._register_missing_toolchain(
                        primary[kind], proposal=proposal
                    )
                else:
                    host_shell_resolution_attempted = True
                    self._resolve_program(primary[kind])
            except ToolError as exc:
                errors[kind] = exc.payload()
        # Registration may have replaced the resolver, so never return the old snapshot.
        discovered = self.toolchains.discover(kinds)
        missing = [kind for kind in kinds
                   if not discovered["toolchains"].get(kind, {}).get("selected")]
        project_contexts = {
            kind: self.toolchains.project_context(primary[kind], self.workspace.root)
            for kind in kinds
            if kind in primary
        }
        return {
            **discovered,
            "project_contexts": project_contexts,
            "shell_startup_files_evaluated": (
                host_shell_resolution_attempted and os.name != "nt"
            ),
            "home_scanned_recursively": False,
            "elevated_user_environment_queried": False,
            "host_resolution": "workspace_aware_desktop_host_resolution",
            "host_user_environment_queried": host_shell_resolution_attempted,
            "host_environment_exposed_to_ai": False,
            "missing": missing,
            "registration_errors": errors,
        }
