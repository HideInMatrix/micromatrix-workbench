from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CLIEntrypointTests(unittest.TestCase):
    def assert_help_succeeds(self, *entrypoint: str) -> None:
        result = subprocess.run(
            [sys.executable, *entrypoint, "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MicroMatrix Workbench", result.stdout)

    def test_package_module_is_the_canonical_entrypoint(self) -> None:
        self.assert_help_succeeds("-m", "agent_workbench")

    def test_cli_module_remains_executable(self) -> None:
        self.assert_help_succeeds("-m", "agent_workbench.cli")

    def test_server_script_shares_the_canonical_cli(self) -> None:
        self.assert_help_succeeds(str(PROJECT_ROOT / "start.py"))

    def test_missing_env_file_reports_a_clean_startup_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_workbench",
                "--env-file",
                str(PROJECT_ROOT / "does-not-exist.env"),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("启动失败", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_server_entrypoint_can_preflight_deployment_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "server.env"
            env_file.write_text(
                "\n".join(
                    (
                        'AGENT_RUNTIME_OAUTH_PASSWORD="password"',
                        'AGENT_RUNTIME_NETWORK_PROVIDER="external"',
                        'AGENT_RUNTIME_SERVER_URL="https://mcp.example.com"',
                    )
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "start.py"),
                    str(root),
                    "--env-file",
                    str(env_file),
                    "--check-config",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("配置检查通过", result.stdout)
        self.assertIn("provider=external", result.stdout)

    def test_server_preflight_rejects_incomplete_cloudflare_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "server.env"
            env_file.write_text(
                "\n".join(
                    (
                        'AGENT_RUNTIME_OAUTH_PASSWORD="password"',
                        'AGENT_RUNTIME_NETWORK_PROVIDER="cloudflare"',
                        'AGENT_RUNTIME_SERVER_URL="https://mcp.example.com"',
                    )
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "start.py"),
                    str(root),
                    "--env-file",
                    str(env_file),
                    "--check-config",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Tunnel Token 必须同时填写", result.stderr)

    def test_server_preflight_rejects_missing_frp_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "server.env"
            env_file.write_text(
                "\n".join(
                    (
                        'AGENT_RUNTIME_OAUTH_PASSWORD="password"',
                        'AGENT_RUNTIME_NETWORK_PROVIDER="frp"',
                        'AGENT_RUNTIME_SERVER_URL="https://mcp.example.com"',
                        f'AGENT_RUNTIME_FRP_CONFIG="{root / "missing.toml"}"',
                    )
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "start.py"),
                    str(root),
                    "--env-file",
                    str(env_file),
                    "--check-config",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("FRP 配置文件不存在", result.stderr)


if __name__ == "__main__":
    unittest.main()
