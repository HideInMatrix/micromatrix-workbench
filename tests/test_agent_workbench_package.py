from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path

import agent_workbench


PUBLIC_EXPORTS = {
    "LaunchConfig",
    "LaunchInfo",
    "MCPLauncher",
    "OAuthClientStore",
    "OAuthClientSummary",
    "MCPServerManager",
    "ManagedServerStatus",
    "MCPServerProfile",
    "ServerProfileStore",
}


class AgentWorkbenchPackageTests(unittest.TestCase):
    def test_public_exports_are_stable(self) -> None:
        self.assertEqual(set(agent_workbench.__all__), PUBLIC_EXPORTS)
        for name in PUBLIC_EXPORTS:
            self.assertIsNotNone(getattr(agent_workbench, name))

    def test_package_module_keeps_cli_entrypoint(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "agent_workbench", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("MicroMatrix", completed.stdout)

    def test_only_explicit_root_compatibility_modules_remain(self) -> None:
        package_root = Path(agent_workbench.__file__).resolve().parent
        self.assertEqual(
            {path.name for path in package_root.glob("*.py")},
            {
                "__init__.py",
                "__main__.py",
                "cli.py",
                "desktop.py",
                "desktop_api.py",
                "mcp_worker.py",
            },
        )

        desktop_api = importlib.import_module("agent_workbench.desktop_api")
        desktop = importlib.import_module("agent_workbench.api.desktop")
        self.assertIs(desktop_api.DesktopAPI, desktop.DesktopAPI)

        removed_internal_modules = (
            "config",
            "gateway_launcher",
            "gateway_manager",
            "gateway_process",
            "gateway_profiles",
            "launcher",
            "mcp_process",
            "network_specs",
            "oauth_client_store",
            "permission_broker",
            "process_utils",
            "resources",
            "self_update",
            "server_manager",
            "server_profiles",
            "user_settings",
            "version",
            "workbench_manager",
        )
        for module_name in removed_internal_modules:
            with self.subTest(module_name=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(f"agent_workbench.{module_name}")

    def test_domain_packages_import_in_clean_interpreter(self) -> None:
        code = (
            "import agent_workbench.core; import agent_workbench.runtime; "
            "import agent_workbench.servers; import agent_workbench.gateways; "
            "import agent_workbench.oauth; import agent_workbench.updates; "
            "import agent_workbench.api"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
