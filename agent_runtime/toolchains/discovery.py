"""Bounded metadata-only lookup for first-use consent. Never source a login shell."""
from __future__ import annotations

import os
from pathlib import Path

from .registration import PROGRAMS, prepare_toolchain


def discover_toolchain(program: str, workspace: Path) -> dict | None:
    if program not in PROGRAMS:
        return None
    home = Path.home()
    # Prefer a project's environment, then the inherited PATH and known manager shims.
    directories = [workspace / '.venv' / 'bin', workspace / 'venv' / 'bin']
    directories += [Path(p) for p in os.environ.get('PATH', '').split(os.pathsep)
                    if p and Path(p).is_absolute()]
    directories += [home / p for p in (
        '.nvmd/bin', '.local/bin', '.volta/bin', '.local/share/mise/shims',
        '.asdf/shims', '.pyenv/shims', '.local/share/pnpm',
    )]
    # Do not guess between multiple installed versions. Manual selection is the fallback.
    pattern = '.nvm/versions/node/*/bin' if program in {'node', 'npm', 'npx', 'pnpm', 'yarn'} else '.pyenv/versions/*/bin'
    versions = list(home.glob(pattern))[:2]
    if len(versions) == 1:
        directories += versions
    for directory in dict.fromkeys(directories):
        path = directory / program
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        try:
            return prepare_toolchain(program, str(path), [])
        except (OSError, ValueError):
            continue
    return None
