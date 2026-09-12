from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from ...errors import ToolError
from ...permissions.capabilities import Capability


class ArtifactHandlers:
    def host_artifact_import_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        host_path = str(args.get("host_path") or "").strip()
        resource_id = "path:" + hashlib.sha256(
            host_path.encode("utf-8", "surrogateescape")
        ).hexdigest()[:32]
        return {
            "authorization_resource": {
                "type": "host_temp_artifact",
                "id": resource_id,
                "name": Path(host_path).name or "Host temporary artifact",
                "identity_fingerprint": resource_id,
                "persistent_authorization_supported": False,
            }
        }

    def _artifact_call(self, parameters: dict[str, Any]) -> dict[str, Any]:
        broker = self.local_permission_broker
        invoke = getattr(broker, "invoke_host_capability", None) if broker is not None else None
        if not callable(invoke):
            raise ToolError(
                "HOST_DISCONNECTED",
                "当前 Runtime 未连接 Workbench Desktop Host Artifact 通道。",
                "runtime",
                True,
                {"capability": "artifact", "action": "read", "stage": "preflight", "cause_code": "HOST_NOT_CONFIGURED"},
            )
        response = invoke("artifact", "read", parameters=parameters)
        if not getattr(response, "ok", False) or not isinstance(getattr(response, "result", None), dict):
            status = str(getattr(response, "status", "error") or "error")
            details = dict(getattr(response, "details", None) or {})
            cause_code = str(details.get("cause_code") or "HOST_ARTIFACT_READ_FAILED")
            details.update({"capability": "artifact", "action": "read", "status": status})
            raise ToolError(
                cause_code,
                str(getattr(response, "error", "") or "Host artifact import failed."),
                "runtime",
                status in {"timeout", "ack_timeout", "unavailable"},
                details,
            )
        return dict(response.result)

    @staticmethod
    def _decode(encoded: str) -> bytes:
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("HOST_ARTIFACT_INVALID", "Host artifact 数据不是有效 Base64。", "runtime") from exc

    def host_artifact_import(self, args: dict[str, Any]) -> dict[str, Any]:
        host_path = str(args.get("host_path") or "").strip()
        destination = str(args.get("destination") or "").strip()
        guessed_mime = mimetypes.guess_type(Path(host_path).name)[0] or "application/octet-stream"
        if not destination and not guessed_mime.startswith("image/"):
            raise ToolError(
                "DESTINATION_REQUIRED",
                "非图片 Host artifact 必须指定当前 Workspace 内的 destination。",
                "validation",
            )
        payload = self._artifact_call(
            {"host_path": host_path, "max_bytes": int(args.get("max_bytes", 25 * 1024 * 1024))}
        )
        encoded = str(payload.pop("data_base64", "") or "")
        data = self._decode(encoded)
        if int(payload.get("bytes", len(data)) or len(data)) != len(data):
            raise ToolError("HOST_ARTIFACT_INVALID", "Host artifact 返回长度与实际内容不一致。", "runtime")
        mime_type = str(payload.get("mime_type") or guessed_mime)
        if destination:
            self._assert_tool_capabilities("host_artifact_import", frozenset({Capability.FILESYSTEM_WRITE}))
            target = self.workspace.writable(destination)
            target.absolute.parent.mkdir(parents=True, exist_ok=True)
            target.absolute.write_bytes(data)
            payload["path"] = target.display
        payload.update({"mime_type": mime_type, "bytes": len(data)})
        if mime_type.startswith("image/"):
            payload["_image"] = (mime_type, encoded)
        return payload


__all__ = ["ArtifactHandlers"]
