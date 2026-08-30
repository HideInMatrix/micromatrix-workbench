#!/usr/bin/env python3
"""Stable server-deployment entry point for MicroMatrix Workbench.

The implementation lives in :mod:`agent_workbench.cli`. Keeping this file thin
preserves ``python start.py`` as a recovery/deployment command without
maintaining a second process and tunnel implementation.
"""

from __future__ import annotations

from agent_workbench.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
