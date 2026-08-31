from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.atomic_io import atomic_write_json, atomic_write_text


class AtomicIOTests(unittest.TestCase):
    def test_json_writer_uses_stable_pretty_format_and_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "state.json"
            atomic_write_text(path, "old")
            atomic_write_json(path, {"b": 2, "a": 1})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1, "b": 2})
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_private_mode_is_preserved_on_posix(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX file modes are not available on Windows")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            atomic_write_json(path, {"secret": True}, mode=0o600)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
