from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .models import ToolchainCandidate
from .paths import system_path_entries


_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")
_PROGRAM_RE = re.compile(r"^[A-Za-z0-9_.+@-]+$")
_PROGRAM_KINDS = {
    "node": "node", "npm": "node", "npx": "node", "corepack": "node",
    "pnpm": "node", "yarn": "node", "python": "python",
    "python3": "python", "pip": "python", "pip3": "python", "go": "go",
    "gofmt": "go",
}

ProbeRunner = Callable[
    [list[str], Mapping[str, str], float],
    subprocess.CompletedProcess[str],
]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(value)
    if match is None:
        return (0, 0, 0)
    parts = [int(item or 0) for item in match.groups()]
    return tuple(parts)  # type: ignore[return-value]


def _normalize_version(value: str) -> str:
    match = _VERSION_RE.search(value.strip())
    if match is None:
        return value.strip().lstrip("v")
    raw_groups = match.groups()
    parts = [str(int(raw_groups[0]))]
    if raw_groups[1] is not None:
        parts.append(str(int(raw_groups[1])))
    if raw_groups[2] is not None:
        parts.append(str(int(raw_groups[2])))
    return ".".join(parts)


class ToolchainResolver:
    """Resolve only configured/registered paths; discovery never grants read access.

    Unrestricted lookup is reserved for Dangerous mode and only uses the inherited
    PATH. Neither mode sources shell startup files or scans the user's Home.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        unrestricted: bool = False,
        safe_path: Sequence[str] | None = None,
        probe_runner: ProbeRunner | None = None,
        registered_programs: Mapping[str, str] | None = None,
    ) -> None:
        self.registered_programs = dict(registered_programs or {})
        self.workspace = workspace.resolve()
        self.unrestricted = unrestricted
        self._safe_path = self._normalize_path_entries(
            safe_path if safe_path is not None else self.default_search_path(self.workspace)
        )
        if unrestricted:
            self._safe_path = self._normalize_path_entries([
                *[p for p in os.environ.get("PATH", "").split(os.pathsep) if Path(p).is_absolute()],
                *self._safe_path,
            ])
        self._probe_runner = probe_runner or self._run_probe_direct
        self._cache: dict[str, dict[str, object]] = {}
        self._program_cache: dict[str, Path | None] = {}

    @classmethod
    def default_search_path(cls, workspace: Path) -> list[str]:
        """Return platform-controlled PATH entries safe to present to a sandbox."""

        root = workspace.resolve()
        raw_entries = cls.system_path_entries()
        result: list[str] = []
        seen: set[str] = set()
        for raw in raw_entries:
            if not raw:
                continue
            try:
                path = Path(raw).expanduser().resolve()
                mode = path.stat().st_mode
            except OSError:
                continue
            key = os.path.normcase(str(path))
            if key in seen or not path.is_dir() or _within(path, root):
                continue
            if mode & stat.S_IWOTH:
                continue
            seen.add(key)
            result.append(str(path))
        return result

    system_path_entries = staticmethod(system_path_entries)

    def discover(
        self,
        kinds: list[str] | None = None,
    ) -> dict[str, object]:
        requested = kinds or ["node", "python", "go"]
        result: dict[str, object] = {}
        for raw_kind in requested:
            kind = raw_kind.strip().lower()
            if kind in {"node", "python", "go"}:
                result[kind] = self._discover_kind(kind)
        return {
            "toolchains": result,
            "safe_path": self.safe_path_entries(result),
            "lookup_scope": "unrestricted" if self.unrestricted else "sandbox",
        }

    def selected(self, kind: str) -> ToolchainCandidate | None:
        payload = self._discover_kind(kind)
        selected = payload.get("selected")
        if not isinstance(selected, dict):
            return None
        return ToolchainCandidate(
            kind=str(selected["kind"]),
            version=str(selected["version"]),
            source=str(selected["source"]),
            root=Path(str(selected["root"])),
            bin_dir=Path(str(selected["bin_dir"])),
            executables={str(k): str(v) for k, v in dict(selected["executables"]).items()},
            selected_reason=str(selected.get("selected_reason") or ""),
        )

    def safe_path_entries(self, discovered: dict[str, object] | None = None) -> list[str]:
        payload = discovered or {
            kind: self._discover_kind(kind)
            for kind in ("node", "python", "go")
        }
        entries: list[str] = []
        for value in payload.values():
            if not isinstance(value, dict):
                continue
            selected = value.get("selected")
            if isinstance(selected, dict):
                entries.append(str(selected.get("bin_dir") or ""))
        entries.extend(self._safe_path)
        return self._normalize_path_entries(entries)

    def resolve_program(self, name: str) -> str | None:
        raw = name.strip()
        if not raw:
            return None
        registered = self.registered_programs.get(raw)
        if registered is not None:
            path = self._validated_executable(Path(registered))
            return str(path) if path is not None else None
        path = Path(raw).expanduser()
        if path.is_absolute():
            resolved = self._validated_executable(path)
            if resolved is None:
                return None
            safe_dirs = {os.path.normcase(item) for item in self.safe_path_entries()}
            if (
                self.unrestricted
                or _within(resolved, self.workspace)
                or os.path.normcase(str(path.parent.resolve())) in safe_dirs
            ):
                return str(resolved)
            return None

        kind = _PROGRAM_KINDS.get(raw)
        if kind is not None:
            payload = self._discover_kind(kind)
            selected = payload.get("selected")
            if isinstance(selected, dict):
                executables = selected.get("executables")
                if isinstance(executables, dict):
                    candidate = executables.get(raw)
                    if isinstance(candidate, str) and self._validated_executable(Path(candidate)):
                        return candidate

        found = self._query_program(raw)
        return str(found) if found is not None else None

    def _discover_kind(self, kind: str) -> dict[str, object]:
        cache_key = kind
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        hint = self._workspace_hint(kind)
        candidates = self._candidates(kind)
        selected = next((self._selected_candidate(c, "explicit desktop registration")
                         for c in candidates if c.source == "registered"), None)
        if selected is None and hint:
            normalized_hint = _normalize_version(hint)
            matches = [item for item in candidates if item.version.startswith(normalized_hint)]
            if matches:
                chosen = max(matches, key=lambda item: _version_key(item.version))
                selected = self._selected_candidate(
                    chosen,
                    f"workspace hint {hint} (configured PATH)",
                )
        if selected is None and candidates:
            selected = self._selected_candidate(
                candidates[0],
                "configured PATH",
            )
        payload = {
            "hint": hint,
            "selected": selected.to_dict() if selected else None,
            "candidates": [item.to_dict() for item in candidates],
            "lookup_scope": "unrestricted" if self.unrestricted else "sandbox",
        }
        self._cache[cache_key] = payload
        return payload

    @staticmethod
    def _selected_candidate(candidate: ToolchainCandidate, reason: str) -> ToolchainCandidate:
        return ToolchainCandidate(
            kind=candidate.kind,
            version=candidate.version,
            source=candidate.source,
            root=candidate.root,
            bin_dir=candidate.bin_dir,
            executables=dict(candidate.executables),
            selected_reason=reason,
        )

    def _workspace_hint(self, kind: str) -> str:
        if kind == "node":
            for name in (".nvmrc", ".node-version"):
                value = self._read_hint(name)
                if value:
                    return value
            try:
                payload = json.loads((self.workspace / "package.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            engines = payload.get("engines") if isinstance(payload, dict) else None
            if isinstance(engines, dict):
                raw = engines.get("node")
                if isinstance(raw, str) and re.fullmatch(r"v?\d+(?:\.\d+){0,2}", raw.strip()):
                    return raw.strip()
            return ""
        if kind == "python":
            return self._read_hint(".python-version")
        if kind == "go":
            direct = self._read_hint(".go-version")
            if direct:
                return direct
            try:
                for line in (self.workspace / "go.mod").read_text(encoding="utf-8").splitlines():
                    if line.startswith("go "):
                        return line.split(None, 1)[1].strip()
            except OSError:
                pass
        return ""

    def _read_hint(self, filename: str) -> str:
        try:
            return (self.workspace / filename).read_text(encoding="utf-8").strip().splitlines()[0]
        except (OSError, IndexError):
            return ""

    def _candidates(self, kind: str) -> list[ToolchainCandidate]:
        primary_names = {
            "node": ["node"], "python": ["python3", "python"], "go": ["go"],
        }[kind]
        executable_names = {
            "node": ["node", "npm", "npx", "corepack", "pnpm", "yarn"],
            "python": ["python", "python3", "pip", "pip3"],
            "go": ["go", "gofmt"],
        }[kind]
        paths: list[tuple[Path, str, Path]] = []
        for name in primary_names:
            executable = self._query_program(name)
            if executable is not None:
                paths.append((
                    executable,
                    "registered" if name in self.registered_programs else "configured_path",
                    executable.parent.parent,
                ))
        return self._build_candidates(
            kind, paths, executable_names,
        )

    def _build_candidates(
        self,
        kind: str,
        paths: list[tuple[Path, str, Path]],
        executable_names: list[str],
    ) -> list[ToolchainCandidate]:
        seen: set[str] = set()
        result: list[ToolchainCandidate] = []
        for candidate, source, root in paths:
            resolved = self._validated_executable(candidate)
            if resolved is None:
                continue
            try:
                bin_dir = candidate.parent.resolve()
                resolved_root = root.expanduser().resolve()
            except OSError:
                continue
            key = os.path.normcase(str(resolved))
            registered = str(resolved) in self.registered_programs.values()
            if key in seen or (not registered and not self._trusted_executable(resolved, bin_dir, resolved_root)):
                continue
            seen.add(key)
            version = self._read_version(
                kind, resolved, bin_dir,
            )
            if not version:
                continue
            executables: dict[str, str] = {}
            for name in executable_names:
                for filename in self._executable_filenames(name):
                    validated = self._validated_executable(bin_dir / filename)
                    if validated is not None:
                        executables[name] = str(validated)
                        break
            result.append(ToolchainCandidate(
                kind=kind,
                version=version,
                source=source,
                root=resolved_root,
                bin_dir=bin_dir,
                executables=executables,
            ))
        return result

    def _query_program(self, name: str) -> Path | None:
        if not _PROGRAM_RE.fullmatch(name):
            return None
        if name in self.registered_programs:
            return self._validated_executable(Path(self.registered_programs[name]))
        if name in self._program_cache:
            return self._program_cache[name]
        # Metadata-only PATH lookup, no command -v, where.exe or login shell.
        for directory in self._safe_path:
            for filename in self._executable_filenames(name):
                candidate = self._validated_executable(Path(directory) / filename)
                if candidate is not None:
                    self._program_cache[name] = candidate
                    return candidate
        self._program_cache[name] = None
        return None

    def _read_version(
        self,
        kind: str,
        executable: Path,
        bin_dir: Path,
    ) -> str:
        args = [str(executable), "--version"] if kind != "go" else [str(executable), "version"]
        env = self._probe_env()
        env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
        try:
            completed = self._probe_runner(args, env, 3.0)
        except (OSError, subprocess.SubprocessError):
            return ""
        if completed.returncode != 0:
            return ""
        return _normalize_version(completed.stdout)

    def _probe_env(self) -> dict[str, str]:
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"LANG", "LC_ALL", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}
        }
        env["HOME"] = str(self.workspace)
        env["PATH"] = os.pathsep.join(self._safe_path)
        env.setdefault("LANG", "C.UTF-8")
        return env

    @staticmethod
    def _run_probe_direct(
        argv: list[str],
        env: Mapping[str, str],
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            shell=False,
            env=dict(env),
        )

    @staticmethod
    def _trusted_executable(executable: Path, bin_dir: Path, root: Path) -> bool:
        try:
            invocation_dir = executable.parent.resolve()
            target = executable.resolve()
            if not _within(invocation_dir, root) and invocation_dir != bin_dir:
                return False
            if not _within(target, root) and not _within(target, bin_dir):
                return False
            return not any(
                path.stat().st_mode & stat.S_IWOTH
                for path in (target, invocation_dir)
            )
        except OSError:
            return False

    @staticmethod
    def _validated_executable(path: Path) -> Path | None:
        try:
            candidate = path.expanduser()
            if not candidate.is_absolute():
                candidate = Path(os.path.abspath(candidate))
            if not candidate.is_file() or (os.name != "nt" and not os.access(candidate, os.X_OK)):
                return None
            # Validate the real target for safety, but preserve the invocation
            # path. Tool managers commonly expose multi-call shims/symlinks
            # (pnpm -> manager binary, node -> manager binary, etc.) whose
            # basename/argv[0] selects the actual tool. Executing the resolved
            # target would silently turn `pnpm build` into `manager build`.
            target = candidate.resolve()
            if target.stat().st_mode & stat.S_IWOTH:
                return None
            return candidate
        except OSError:
            return None

    @staticmethod
    def _normalize_path_entries(entries: Sequence[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in entries:
            if not raw:
                continue
            try:
                path = Path(raw).expanduser().resolve()
            except OSError:
                continue
            key = os.path.normcase(str(path))
            if key not in seen and path.is_dir():
                seen.add(key)
                result.append(str(path))
        return result

    @staticmethod
    def _executable_filenames(name: str) -> list[str]:
        if os.name == "nt":
            return [f"{name}.exe", f"{name}.cmd", f"{name}.bat", name]
        return [name]
