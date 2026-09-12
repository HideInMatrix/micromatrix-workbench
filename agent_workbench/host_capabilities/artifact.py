from __future__ import annotations

import base64
import hashlib
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

from .base import HostCapabilityDescriptor, HostCapabilityError


DEFAULT_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024


class HostArtifactCapability:
    """Bounded bridge for files generated in the Host temporary directory.

    External desktop applications and MCP servers frequently return Host-side
    temporary paths that the Runtime sandbox cannot read.  This provider does
    not expose arbitrary Host filesystem reads: after resolving symlinks the
    source must remain under the current user's OS temp root and the payload is
    size bounded before it crosses the signed Host Capability channel.
    """

    descriptor = HostCapabilityDescriptor(
        name="artifact",
        provider="host_temp_artifact_bridge",
        session_based=False,
        operations=("read",),
    )

    def __init__(self) -> None:
        self._temp_root = Path(tempfile.gettempdir()).resolve()

    def _resolve_source(self, raw_path: str) -> Path:
        value = raw_path.strip()
        if not value:
            raise HostCapabilityError(
                "artifact.read 需要 host_path。",
                code="HOST_ARTIFACT_ARGUMENT_INVALID",
                stage="preflight",
            )
        candidate = Path(value)
        if not candidate.is_absolute():
            raise HostCapabilityError(
                "Host artifact path 必须是绝对路径。",
                code="HOST_ARTIFACT_PATH_INVALID",
                stage="preflight",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise HostCapabilityError(
                f"Host artifact 不存在或无法读取: {value}",
                code="HOST_ARTIFACT_NOT_FOUND",
                stage="artifact_resolution",
            ) from exc
        try:
            resolved.relative_to(self._temp_root)
        except ValueError as exc:
            raise HostCapabilityError(
                "Host artifact bridge 只允许读取当前用户 OS 临时目录中的产物。",
                code="HOST_ARTIFACT_OUTSIDE_TEMP_ROOT",
                stage="policy",
            ) from exc
        if not resolved.is_file():
            raise HostCapabilityError(
                "Host artifact path 不是普通文件。",
                code="HOST_ARTIFACT_NOT_FILE",
                stage="artifact_resolution",
            )
        return resolved

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del server_id, session_id
        if action != "read":
            raise HostCapabilityError(
                f"artifact 不支持 action: {action}",
                code="HOST_ARTIFACT_ACTION_UNSUPPORTED",
                stage="preflight",
            )
        source = self._resolve_source(str(parameters.get("host_path") or ""))
        max_bytes = max(
            1,
            min(int(parameters.get("max_bytes", DEFAULT_MAX_ARTIFACT_BYTES)), MAX_ARTIFACT_BYTES),
        )
        try:
            stat = source.stat()
        except OSError as exc:
            raise HostCapabilityError(
                "无法读取 Host artifact 元数据。",
                code="HOST_ARTIFACT_READ_FAILED",
                stage="artifact_read",
            ) from exc
        if stat.st_size > max_bytes:
            raise HostCapabilityError(
                f"Host artifact 超过大小限制: {stat.st_size} > {max_bytes} bytes。",
                code="HOST_ARTIFACT_TOO_LARGE",
                stage="policy",
            )
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise HostCapabilityError(
                "无法读取 Host artifact。",
                code="HOST_ARTIFACT_READ_FAILED",
                stage="artifact_read",
            ) from exc
        if len(data) > max_bytes:
            raise HostCapabilityError(
                f"Host artifact 超过大小限制: {len(data)} > {max_bytes} bytes。",
                code="HOST_ARTIFACT_TOO_LARGE",
                stage="policy",
            )
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return {
            "host_path": str(source),
            "name": source.name,
            "bytes": len(data),
            "mime_type": mime_type,
            "sha256": hashlib.sha256(data).hexdigest(),
            "data_base64": base64.b64encode(data).decode("ascii"),
            "source_scope": "host_temp",
        }

    def close_server(self, server_id: str) -> None:
        del server_id

    def close(self) -> None:
        return None


__all__ = [
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_BYTES",
    "HostArtifactCapability",
]
