from __future__ import annotations

import unittest
from pathlib import Path

from agent_runtime.server import HEALTH_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


class ServerDependencyTests(unittest.TestCase):
    def test_server_requirements_exclude_desktop_tooling(self) -> None:
        requirements = read("requirements-server.txt").lower().splitlines()

        self.assertTrue(any(item.startswith("pillow") for item in requirements))
        self.assertTrue(any(item.startswith("certifi") for item in requirements))
        self.assertFalse(any("pywebview" in item for item in requirements))
        self.assertFalse(any("pyinstaller" in item for item in requirements))


class SystemdDeploymentTests(unittest.TestCase):
    def test_project_service_is_preflighted_and_hardened(self) -> None:
        unit = read("deploy/linux/micromatrix-workbench.service")

        self.assertIn("User=micromatrix", unit)
        self.assertIn("ExecStartPre=", unit)
        self.assertIn("--check-config", unit)
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("AGENT_RUNTIME", read("deploy/linux/server.env.example"))

    def test_audit_service_exposes_curated_read_only_host_view(self) -> None:
        unit = read("deploy/linux/micromatrix-workbench-audit.service")
        directives = [
            line.strip()
            for line in unit.splitlines()
            if line.startswith("BindReadOnlyPaths=")
        ]

        self.assertGreaterEqual(len(directives), 20)
        self.assertIn("/srv/micromatrix-audit", unit)
        self.assertIn("--port 8235", unit)
        self.assertIn("ReadWritePaths=/srv/micromatrix-audit/reports", unit)
        self.assertTrue(any("/etc/ssh/sshd_config:" in item for item in directives))
        self.assertTrue(any("/proc/sys:" in item for item in directives))
        self.assertFalse(any("/etc/shadow:" in item for item in directives))
        self.assertFalse(any("/var/run/docker.sock:" in item for item in directives))
        self.assertNotIn("User=root", unit)
        self.assertIn("NoNewPrivileges=true", unit)


class DockerDeploymentTests(unittest.TestCase):
    def test_server_image_is_headless_non_root_and_health_checked(self) -> None:
        dockerfile = read("deploy/docker/Dockerfile")
        dockerignore = read(".dockerignore")

        self.assertIn("FROM python:3.13-slim-bookworm", dockerfile)
        self.assertIn("requirements-server.txt", dockerfile)
        self.assertIn("USER micromatrix:micromatrix", dockerfile)
        self.assertIn("ENTRYPOINT", dockerfile)
        self.assertIn("start.py", dockerfile)
        self.assertIn(HEALTH_PATH, dockerfile)
        self.assertNotIn("requirements-desktop.txt", dockerfile)
        self.assertNotIn("desktop.py", dockerfile)
        self.assertIn("agent_workbench/web", dockerignore)

    def test_compose_keeps_origin_local_and_state_persistent(self) -> None:
        compose = read("deploy/docker/compose.yaml")

        self.assertIn('127.0.0.1:${MICROMATRIX_PORT:-8234}:8234', compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn("target: /var/lib/micromatrix", compose)
        self.assertNotIn("privileged: true", compose)
        self.assertNotIn("docker.sock", compose)


class ServerDeploymentDocumentationTests(unittest.TestCase):
    def test_dedicated_guide_links_every_deployment_asset(self) -> None:
        guide = read("docs/SERVER_DEPLOYMENT.md")

        for value in (
            "requirements-server.txt",
            "micromatrix-workbench.service",
            "micromatrix-workbench-audit.service",
            "deploy/docker",
            "--check-config",
            HEALTH_PATH,
            "升级与回滚",
            "Docker Socket",
        ):
            self.assertIn(value, guide)

        self.assertIn("docs/SERVER_DEPLOYMENT.md", read("README.md"))
        self.assertIn("SERVER_DEPLOYMENT.md", read("docs/USER_GUIDE.md"))


if __name__ == "__main__":
    unittest.main()
