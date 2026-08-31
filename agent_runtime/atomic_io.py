"""Small, dependency-free atomic file writers shared by runtime layers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, *, mode: int | None = None) -> None:
    """Write UTF-8 text through a same-directory temporary file and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(raw_temporary)
    try:
        if mode is not None and os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if mode is not None and os.name != "nt":
            path.chmod(mode)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    mode: int | None = None,
    compact: bool = False,
    trailing_newline: bool = True,
) -> None:
    """Serialize JSON with the project's stable formatting and atomically replace."""

    if compact:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if trailing_newline:
        encoded += "\n"
    atomic_write_text(path, encoded, mode=mode)
