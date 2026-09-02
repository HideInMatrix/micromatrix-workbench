from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from agent_runtime.local_permission_broker import (
    BROKER_DIR_ENV,
    BROKER_SECRET_ENV,
    BROKER_SERVER_ID_ENV,
)

from ..core.resources import PROJECT_ROOT, is_frozen
from ..oauth.persistence import (
    OAuthPersistence,
    bind_server_oauth_issuer,
    prepare_ephemeral_oauth_persistence,
    prepare_issuer_oauth_persistence,
)
from ..runtime.mcp_process import INTERNAL_MCP_FLAG
from ..runtime.process import (
    LogCallback,
    forward_process_output,
    hidden_process_kwargs,
    stop_process,
    wait_for_tcp_port,
)
from .models import GatewayProcessConfig


@dataclass(slots=True)
class PreparedGatewayConfig:
    config_file: Path
    temporary_dir: Path
    persistences: tuple[OAuthPersistence, ...]
    registry_files: dict[str, Path]
    issuer_bindings: tuple[tuple[str, str], ...]

    def remove_config_file(self) -> None:
        try:
            self.config_file.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup(self) -> None:
        self.remove_config_file()
        for persistence in self.persistences:
            persistence.cleanup()
        shutil.rmtree(self.temporary_dir, ignore_errors=True)


def prepare_gateway_config(
    config: GatewayProcessConfig,
    *,
    permission_broker: object | None = None,
) -> PreparedGatewayConfig:
    validated = config.validated()
    directory = Path(tempfile.mkdtemp(prefix="micromatrix-workbench-gateway-"))
    try:
        if os.name != "nt":
            directory.chmod(0o700)
        profile_payloads: list[dict[str, object]] = []
        persistences: list[OAuthPersistence] = []
        registry_files: dict[str, Path] = {}
        issuer_bindings: list[tuple[str, str]] = []
        for profile in validated.profiles:
            issuer = profile.public_url or f"{validated.public_base_url}{profile.instance_path}"
            if profile.lifecycle == "ephemeral":
                persistence = prepare_ephemeral_oauth_persistence(profile.server_id)
            else:
                persistence = prepare_issuer_oauth_persistence(issuer)
                issuer_bindings.append((profile.server_id, issuer))
            persistences.append(persistence)
            registry_files[profile.server_id] = persistence.registry_file
            profile_payload: dict[str, object] = {
                    "profile_id": profile.server_id,
                    "instance_path": profile.instance_path,
                    "public_url": profile.public_url,
                    "workspace": str(profile.workspace),
                    "permission_mode": profile.permission_mode,
                    "allow_network": profile.allow_network,
                    "enable_view_image": profile.enable_view_image,
                    "oauth": {
                        "password": profile.oauth_password,
                        "server_url": issuer,
                        "token_secret_hex": persistence.token_secret_hex,
                        "registry_file": str(persistence.registry_file),
                        "cimd_enabled": profile.lifecycle != "ephemeral",
                    },
                }
            if permission_broker is not None:
                child_environment = getattr(permission_broker, "child_environment", None)
                if not callable(child_environment):
                    raise ValueError("permission_broker does not provide child_environment")
                broker_env = child_environment(profile.server_id)
                if not isinstance(broker_env, dict):
                    raise ValueError("permission_broker child_environment must return a dict")
                broker_directory = str(
                    broker_env.get(BROKER_DIR_ENV) or ""
                ).strip()
                secret = str(broker_env.get(BROKER_SECRET_ENV) or "").strip()
                server_id = str(
                    broker_env.get(BROKER_SERVER_ID_ENV) or profile.server_id
                ).strip()
                if broker_directory and secret:
                    profile_payload["permission_broker"] = {
                        "directory": broker_directory,
                        "secret_hex": secret,
                        "server_id": server_id,
                    }
            profile_payloads.append(profile_payload)
        config_file = directory / "gateway.json"
        config_file.write_text(
            json.dumps(
                {"version": 1, "profiles": profile_payloads},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            config_file.chmod(0o600)
        return PreparedGatewayConfig(
            config_file=config_file,
            temporary_dir=directory,
            persistences=tuple(persistences),
            registry_files=registry_files,
            issuer_bindings=tuple(issuer_bindings),
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def build_gateway_mcp_command(
    config: GatewayProcessConfig,
    gateway_config_file: Path,
) -> list[str]:
    validated = config.validated()
    arguments = [
        "--host",
        validated.host,
        "--port",
        str(validated.port),
        "--gateway-config",
        str(gateway_config_file),
    ]
    if is_frozen():
        return [sys.executable, INTERNAL_MCP_FLAG, *arguments]
    return [sys.executable, "-m", "agent_workbench.mcp_worker", *arguments]


class GatewayServerProcess:
    def __init__(self, log: LogCallback, *, permission_broker: object | None = None):
        self._log = log
        self._permission_broker = permission_broker
        self.process: subprocess.Popen[str] | None = None
        self._prepared: PreparedGatewayConfig | None = None

    def start(self, config: GatewayProcessConfig, env: dict[str, str]) -> None:
        validated = config.validated()
        prepared = prepare_gateway_config(
            validated,
            permission_broker=self._permission_broker,
        )
        self._prepared = prepared
        command = build_gateway_mcp_command(validated, prepared.config_file)
        self._log(
            f"启动 Local MCP Gateway，Profiles: {len(validated.profiles)}，"
            f"监听 {validated.host}:{validated.port}"
        )
        try:
            self.process = subprocess.Popen(
                command,
                env=env,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **hidden_process_kwargs(),
            )
            forward_process_output(self.process, prefix="gateway", log=self._log)
            wait_for_tcp_port(
                validated.host,
                validated.port,
                process=self.process,
            )
            # The child loads the whole config before binding. Remove passwords
            # and token secrets from the temporary filesystem as soon as the
            # listening socket proves startup completed.
            prepared.remove_config_file()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        stop_process(self.process, name="agent-runtime-gateway", log=self._log)
        self.process = None
        prepared = self._prepared
        self._prepared = None
        if prepared is not None:
            prepared.cleanup()

    def bind_oauth_issuers(self) -> None:
        """Commit management bindings after origin and provider startup."""

        prepared = self._prepared
        if prepared is None:
            return
        for server_id, issuer in prepared.issuer_bindings:
            bind_server_oauth_issuer(server_id, issuer)

    def oauth_registry_file(self, server_id: str) -> Path | None:
        prepared = self._prepared
        if prepared is None:
            return None
        return prepared.registry_files.get(server_id.strip())
