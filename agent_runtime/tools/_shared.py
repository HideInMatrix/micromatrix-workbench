from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ToolError


MAX_MCP_IMAGE_BYTES = 25 * 1024 * 1024


def decode_png_base64(encoded: str, *, label: str = "Image") -> bytes:
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(
            "HOST_CAPABILITY_ERROR",
            f"{label} 返回无效 PNG 数据。",
            "runtime",
        ) from exc
    if len(data) > MAX_MCP_IMAGE_BYTES:
        raise ToolError(
            "OUTPUT_TOO_LARGE",
            f"{label} 超过 25 MiB 限制。",
            "runtime",
        )
    return data


def attach_png_image(
    payload: dict[str, Any],
    *,
    field: str = "data_base64",
    label: str = "Image",
) -> dict[str, Any]:
    encoded = str(payload.pop(field, "") or "")
    if not encoded:
        return payload
    data = decode_png_base64(encoded, label=label)
    payload.setdefault("mime_type", "image/png")
    payload["bytes"] = len(data)
    payload["_image"] = ("image/png", encoded)
    return payload


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    raw = text.encode("utf-8", "replace")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", "ignore"), True


def iso_mtime(path: Path) -> str:
    try:
        return (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except OSError:
        return ""


def parse_git_branch_line(line: str) -> tuple[str, str, int, int]:
    branch = line
    upstream = ""
    ahead = 0
    behind = 0
    if "..." in line:
        branch, rest = line.split("...", 1)
        upstream = rest.split(" ", 1)[0]
    if "[" in line and "]" in line:
        meta = line.split("[", 1)[1].split("]", 1)[0]
        ahead_match = re.search(r"ahead (\d+)", meta)
        behind_match = re.search(r"behind (\d+)", meta)
        ahead = int(ahead_match.group(1)) if ahead_match else 0
        behind = int(behind_match.group(1)) if behind_match else 0
    return branch.strip(), upstream.strip(), ahead, behind


def parse_diff_files(diff_text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                current = {"path": path, "status": "modified", "binary": False}
                files.append(current)
        elif current is not None and line.startswith("new file mode"):
            current["status"] = "added"
        elif current is not None and line.startswith("deleted file mode"):
            current["status"] = "deleted"
        elif current is not None and line.startswith("Binary files"):
            current["binary"] = True
    return files
