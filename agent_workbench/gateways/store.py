from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.atomic_io import atomic_write_json

from ..core.config import DEFAULT_HOST, DEFAULT_PORT, NetworkConfig
from ..core.settings import settings_dir
from .models import MCPGatewayMember, MCPGatewayProfile, _public_hostname, _timestamp


GATEWAY_PROFILE_SCHEMA_VERSION = 1


class GatewayProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings_dir() / "gateways.json")

    def list(self) -> list[MCPGatewayProfile]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gateway Profile 文件损坏: {self.path}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != GATEWAY_PROFILE_SCHEMA_VERSION
        ):
            raise RuntimeError(f"Gateway Profile 文件格式不受支持: {self.path}")
        raw_gateways = payload.get("gateways")
        if not isinstance(raw_gateways, list):
            raise RuntimeError(f"Gateway Profile gateways 字段无效: {self.path}")
        try:
            return [
                MCPGatewayProfile.from_dict(item)
                for item in raw_gateways
                if isinstance(item, dict)
            ]
        except ValueError as exc:
            raise RuntimeError(f"Gateway Profile 内容无效: {self.path}") from exc

    def get(self, gateway_id: str) -> MCPGatewayProfile | None:
        target = gateway_id.strip()
        return next(
            (gateway for gateway in self.list() if gateway.gateway_id == target),
            None,
        )

    def create(
        self,
        *,
        name: str,
        network: NetworkConfig,
        members: tuple[MCPGatewayMember, ...],
        mode: str = "multi",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> MCPGatewayProfile:
        gateway = MCPGatewayProfile.create(
            name=name,
            network=network,
            members=members,
            mode=mode,
            host=host,
            port=port,
        )
        gateways = self.list()
        gateways.append(gateway)
        self._save(gateways)
        return gateway

    def save(self, gateway: MCPGatewayProfile) -> MCPGatewayProfile:
        validated = gateway.validated()
        replacement = MCPGatewayProfile(
            gateway_id=validated.gateway_id,
            name=validated.name,
            network=validated.network,
            members=validated.members,
            mode=validated.mode,
            host=validated.host,
            port=validated.port,
            created_at=validated.created_at,
            updated_at=_timestamp(),
        )
        gateways = self.list()
        for index, existing in enumerate(gateways):
            if existing.gateway_id == replacement.gateway_id:
                gateways[index] = replacement
                self._save(gateways)
                return replacement
        gateways.append(replacement)
        self._save(gateways)
        return replacement

    def delete(self, gateway_id: str) -> bool:
        target = gateway_id.strip()
        gateways = self.list()
        remaining = [item for item in gateways if item.gateway_id != target]
        if len(remaining) == len(gateways):
            return False
        self._save(remaining)
        return True

    def next_default_port(self, start: int = DEFAULT_PORT) -> int:
        used = {gateway.port for gateway in self.list()}
        for port in range(max(1, int(start)), 65536):
            if port not in used:
                return port
        raise RuntimeError("没有可用的 Gateway TCP 端口可分配。")

    def _save(self, gateways: list[MCPGatewayProfile]) -> None:
        ids: set[str] = set()
        endpoints: set[tuple[str, int]] = set()
        hostnames: set[str] = set()
        member_ids: set[str] = set()
        validated: list[MCPGatewayProfile] = []
        for gateway in gateways:
            item = gateway.validated()
            if item.gateway_id in ids:
                raise ValueError(f"重复 gateway_id: {item.gateway_id}")
            ids.add(item.gateway_id)
            endpoint = (item.host, item.port)
            if endpoint in endpoints:
                raise ValueError(
                    f"多个 Gateway 不能配置相同地址: {item.host}:{item.port}"
                )
            endpoints.add(endpoint)
            gateway_hostnames = {
                hostname
                for hostname in (
                    _public_hostname(item.network.public_url),
                    *(_public_hostname(member.public_url) for member in item.members),
                )
                if hostname
            }
            overlap = hostnames.intersection(gateway_hostnames)
            if overlap:
                raise ValueError(
                    f"多个 Gateway 不能配置相同 Public Hostname: {sorted(overlap)[0]}"
                )
            hostnames.update(gateway_hostnames)
            for member in item.members:
                if member.server_id in member_ids:
                    raise ValueError(
                        f"Gateway Member server_id 必须全局唯一: {member.server_id}"
                    )
                member_ids.add(member.server_id)
            validated.append(item)

        payload = {
            "version": GATEWAY_PROFILE_SCHEMA_VERSION,
            "gateways": [item.to_dict() for item in validated],
        }
        atomic_write_json(self.path, payload, mode=0o600)
