from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_workbench.config import LaunchConfig, NetworkConfig
from agent_workbench.cloudflared import is_request_cancellation_log
from agent_workbench.launcher import MCPLauncher
from agent_workbench.network.external import ExternalUrlProvider
from agent_workbench.network.base import NetworkProviderResult
from agent_workbench.network.factory import create_network_provider
from agent_workbench.network.frp import FrpProvider
from agent_workbench.network.ngrok import NgrokProvider


class NetworkConfigTests(unittest.TestCase):
    def test_launch_config_requires_only_oauth_password_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig(
                workspace=Path(temporary),
                oauth_password="password",
                network=NetworkConfig(
                    provider="external",
                    public_url="https://mcp.example.com",
                ),
            ).validated()
        self.assertEqual(config.oauth_password, "password")
        self.assertFalse(hasattr(config, "oauth_client_id"))
        self.assertFalse(hasattr(config, "oauth_client_secret"))

    def test_public_url_is_normalized(self) -> None:
        config = NetworkConfig(
            provider="external",
            public_url="https://mcp.example.com/mcp/",
        ).validated()
        self.assertEqual(config.public_url, "https://mcp.example.com")

    def test_cloudflared_context_cancellation_is_classified_as_request_level(self) -> None:
        self.assertTrue(
            is_request_cancellation_log(
                'ERR error="Incoming request ended abruptly: context canceled" connIndex=3'
            )
        )
        self.assertTrue(
            is_request_cancellation_log(
                'ERR failed to serve incoming request error="Failed to proxy HTTP: '
                'Incoming request ended abruptly: context canceled"'
            )
        )
        self.assertFalse(
            is_request_cancellation_log("ERR Unable to reach the origin service")
        )

    def test_launch_config_keeps_provider_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig(
                workspace=Path(temporary),
                oauth_password="password",
                network=NetworkConfig(
                    provider="frp",
                    public_url="https://mcp.example.com",
                    options={"config_file": " ./frpc.toml "},
                ),
            ).validated()
        self.assertEqual(config.network.provider, "frp")
        self.assertEqual(config.network.options["config_file"], "./frpc.toml")

    def test_from_env_builds_ngrok_provider_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    # Legacy values are intentionally ignored. OAuth clients
                    # are always created through Dynamic Client Registration.
                    "AGENT_RUNTIME_OAUTH_CLIENT_ID": "client",
                    "AGENT_RUNTIME_OAUTH_CLIENT_SECRET": "secret",
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "ngrok",
                    "AGENT_RUNTIME_NGROK": "/opt/ngrok",
                    "AGENT_RUNTIME_NGROK_AUTHTOKEN": "token",
                },
            )
        self.assertEqual(config.network.provider, "ngrok")
        self.assertEqual(config.network.options["executable"], "/opt/ngrok")
        self.assertEqual(config.network.options["authtoken"], "token")
        self.assertFalse(hasattr(config, "oauth_client_id"))
        self.assertFalse(hasattr(config, "oauth_client_secret"))

    def test_from_env_uses_ephemeral_oauth_for_random_tunnel_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quick_tunnel = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "cloudflare",
                },
            )
            named_tunnel = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "cloudflare",
                    "AGENT_RUNTIME_SERVER_URL": "https://mcp.example.com",
                    "AGENT_RUNTIME_TUNNEL_TOKEN": "token",
                },
            )

        self.assertEqual(quick_tunnel.lifecycle, "ephemeral")
        self.assertEqual(named_tunnel.lifecycle, "persistent")

    def test_from_env_passes_only_non_reserved_runtime_knobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "cloudflare",
                    "AGENT_RUNTIME_TUNNEL_TOKEN": "provider-secret",
                    "AGENT_RUNTIME_OS_SANDBOX": "require",
                    "AGENT_RUNTIME_ALLOWED_ORIGINS": "https://client.example.com",
                    "UNRELATED_VALUE": "ignored",
                },
            )

        self.assertEqual(
            config.runtime_environment,
            {
                "AGENT_RUNTIME_OS_SANDBOX": "require",
                "AGENT_RUNTIME_ALLOWED_ORIGINS": "https://client.example.com",
            },
        )

    def test_from_env_allows_dynamic_client_registration_without_client_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "external",
                    "AGENT_RUNTIME_SERVER_URL": "https://mcp.example.com",
                },
            )
        self.assertFalse(hasattr(config, "oauth_client_id"))
        self.assertFalse(hasattr(config, "oauth_client_secret"))

    def test_from_env_keeps_cloudflare_instance_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig.from_env(
                workspace=Path(temporary),
                env={
                    "AGENT_RUNTIME_OAUTH_PASSWORD": "password",
                    "AGENT_RUNTIME_NETWORK_PROVIDER": "cloudflare",
                    "AGENT_RUNTIME_SERVER_URL": "https://mcp.example.com/company/mcp",
                    "AGENT_RUNTIME_TUNNEL_TOKEN": "company-token",
                },
            )

        self.assertEqual(config.network.public_url, "https://mcp.example.com/company")
        self.assertEqual(config.network.options["tunnel_token"], "company-token")


class ProviderTests(unittest.TestCase):
    @staticmethod
    def _provider(events: list[str], public_url: str):
        provider = MagicMock()
        provider.display_name = "Fake Provider"
        provider.is_running = True
        provider.exit_code = None

        def start(_host, _port, _config):
            events.append("provider")
            return NetworkProviderResult("fake", public_url, "Fake Provider")

        provider.start.side_effect = start
        return provider

    def test_factory_returns_requested_provider(self) -> None:
        provider = create_network_provider("external", lambda _message: None)
        self.assertIsInstance(provider, ExternalUrlProvider)

    def test_external_provider_has_no_child_process(self) -> None:
        logs: list[str] = []
        provider = ExternalUrlProvider(logs.append)
        result = provider.start(
            "127.0.0.1",
            8234,
            NetworkConfig(provider="external", public_url="https://mcp.example.com").validated(),
        )
        self.assertTrue(provider.is_running)
        self.assertEqual(result.public_base_url, "https://mcp.example.com")
        provider.stop()
        self.assertFalse(provider.is_running)

    def test_frp_requires_public_url_and_config_file(self) -> None:
        provider = FrpProvider(lambda _message: None)
        with self.assertRaisesRegex(ValueError, "Public URL"):
            provider.start("127.0.0.1", 8234, NetworkConfig(provider="frp"))

        with self.assertRaisesRegex(ValueError, "配置文件"):
            with patch.object(provider, "resolve_executable", return_value=Path("frpc")):
                provider.start(
                    "127.0.0.1",
                    8234,
                    NetworkConfig(
                        provider="frp",
                        public_url="https://mcp.example.com",
                    ).validated(),
                )

    def test_ngrok_extracts_url_from_json_and_text(self) -> None:
        provider = NgrokProvider(lambda _message: None)
        self.assertEqual(
            provider._extract_url('{"url":"https://demo.ngrok.app"}'),
            "https://demo.ngrok.app",
        )
        self.assertEqual(
            provider._extract_url("started tunnel https://demo.ngrok.app -> localhost"),
            "https://demo.ngrok.app",
        )

    def test_named_tunnel_probe_preserves_instance_path(self) -> None:
        launcher = MCPLauncher()
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with (
            patch(
                "agent_workbench.launcher.urllib.request.urlopen",
                return_value=response,
            ) as urlopen,
            patch("agent_workbench.launcher.time.sleep"),
        ):
            launcher._verify_named_tunnel_route(
                "https://mcp.example.com/company",
                "probe-token",
                attempts=3,
            )

        request = urlopen.call_args_list[0].args[0]
        self.assertTrue(
            request.full_url.startswith(
                "https://mcp.example.com/company/.well-known/micromatrix-workbench-route-probe?nonce="
            )
        )

    def test_named_tunnel_probe_reports_public_hostname_mismatch(self) -> None:
        launcher = MCPLauncher()
        error = urllib.error.HTTPError(
            "https://mcp.example.com/company/.well-known/micromatrix-workbench-route-probe",
            404,
            "Not Found",
            None,
            None,
        )
        with patch(
            "agent_workbench.launcher.urllib.request.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(RuntimeError, "Public Hostname"):
                launcher._verify_named_tunnel_route(
                    "https://mcp.example.com/company",
                    "probe-token",
                    attempts=1,
                )

    def test_named_tunnel_probe_403_is_inconclusive_not_failure(self) -> None:
        logs: list[str] = []
        launcher = MCPLauncher(logs.append)
        error = urllib.error.HTTPError(
            "https://mcp.example.com/.well-known/micromatrix-workbench-route-probe",
            403,
            "Forbidden",
            None,
            None,
        )
        with patch(
            "agent_workbench.launcher.urllib.request.urlopen",
            side_effect=error,
        ):
            launcher._verify_named_tunnel_route(
                "https://mcp.example.com",
                "probe-token",
                attempts=1,
            )

        self.assertEqual(len(logs), 1)
        self.assertIn("HTTP 403", logs[0])
        self.assertIn("不据此判断 MCP 公网连接不可用", logs[0])

    def test_named_tunnel_probe_background_is_non_fatal(self) -> None:
        logs: list[str] = []
        launcher = MCPLauncher(logs.append)
        with patch.object(
            launcher,
            "_verify_named_tunnel_route",
            side_effect=RuntimeError("Public Hostname returned 404"),
        ):
            launcher._verify_named_tunnel_route_background(
                "https://mcp.example.com/company",
                "probe-token",
            )

        self.assertEqual(len(logs), 1)
        self.assertIn("保持运行", logs[0])
        self.assertIn("Public Hostname returned 404", logs[0])

    def test_stable_public_url_starts_runtime_before_provider(self) -> None:
        events: list[str] = []
        captured_env: dict[str, str] = {}
        provider = self._provider(events, "https://mcp.example.com")
        launcher = MCPLauncher()
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig(
                workspace=Path(temporary),
                oauth_password="password",
                network=NetworkConfig(
                    provider="external",
                    public_url="https://mcp.example.com",
                ),
                runtime_environment={
                    "AGENT_RUNTIME_OS_SANDBOX": "require",
                    "AGENT_RUNTIME_SERVER_URL": "https://wrong.example.com",
                },
            )

            def start_runtime(_config, env):
                events.append("runtime")
                captured_env.update(env)

            with (
                patch("agent_workbench.launcher.check_port_available"),
                patch(
                    "agent_workbench.launcher.create_network_provider",
                    return_value=provider,
                ),
                patch(
                    "agent_workbench.launcher.prepare_issuer_oauth_persistence"
                ) as persistence,
                patch.object(launcher._mcp, "start", side_effect=start_runtime),
            ):
                persistence.return_value.registry_file = Path(temporary) / "clients.json"
                persistence.return_value.token_secret_hex = "11" * 32
                persistence.return_value.ephemeral = False
                launcher.start(config)
                launcher.stop()

        self.assertEqual(events, ["runtime", "provider"])
        self.assertEqual(captured_env["AGENT_RUNTIME_OS_SANDBOX"], "require")
        self.assertEqual(
            captured_env["AGENT_RUNTIME_SERVER_URL"],
            "https://mcp.example.com",
        )
        self.assertEqual(
            captured_env["AGENT_RUNTIME_OAUTH_TOKEN_SECRET"],
            "11" * 32,
        )

    def test_dynamic_public_url_starts_provider_before_runtime(self) -> None:
        events: list[str] = []
        provider = self._provider(events, "https://random.example.com")
        launcher = MCPLauncher()
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig(
                workspace=Path(temporary),
                oauth_password="password",
                network=NetworkConfig(provider="cloudflare"),
                lifecycle="ephemeral",
            )
            with (
                patch("agent_workbench.launcher.check_port_available"),
                patch(
                    "agent_workbench.launcher.create_network_provider",
                    return_value=provider,
                ),
                patch(
                    "agent_workbench.launcher.prepare_ephemeral_oauth_persistence"
                ) as persistence,
                patch.object(
                    launcher._mcp,
                    "start",
                    side_effect=lambda _config, _env: events.append("runtime"),
                ),
            ):
                persistence.return_value.registry_file = Path(temporary) / "clients.json"
                persistence.return_value.token_secret_hex = "22" * 32
                persistence.return_value.ephemeral = True
                launcher.start(config)
                launcher.stop()

        self.assertEqual(events, ["provider", "runtime"])

    def test_stable_provider_mismatch_rolls_back_without_binding(self) -> None:
        events: list[str] = []
        provider = self._provider(events, "https://wrong.example.com")
        provider.stop.side_effect = lambda: events.append("provider-stop")
        launcher = MCPLauncher()
        with tempfile.TemporaryDirectory() as temporary:
            config = LaunchConfig(
                workspace=Path(temporary),
                oauth_password="password",
                network=NetworkConfig(
                    provider="external",
                    public_url="https://mcp.example.com",
                ),
                server_id="server-a",
            )
            with (
                patch("agent_workbench.launcher.check_port_available"),
                patch(
                    "agent_workbench.launcher.create_network_provider",
                    return_value=provider,
                ),
                patch(
                    "agent_workbench.launcher.prepare_issuer_oauth_persistence"
                ) as persistence,
                patch(
                    "agent_workbench.launcher.bind_server_oauth_issuer"
                ) as bind_issuer,
                patch.object(
                    launcher._mcp,
                    "start",
                    side_effect=lambda _config, _env: events.append("runtime"),
                ),
                patch.object(
                    launcher._mcp,
                    "stop",
                    side_effect=lambda: events.append("runtime-stop"),
                ),
            ):
                persistence.return_value.registry_file = Path(temporary) / "clients.json"
                persistence.return_value.token_secret_hex = "33" * 32
                persistence.return_value.ephemeral = False
                with self.assertRaisesRegex(RuntimeError, "OAuth issuer"):
                    launcher.start(config)

        self.assertEqual(
            events,
            ["runtime", "provider", "runtime-stop", "provider-stop"],
        )
        bind_issuer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
