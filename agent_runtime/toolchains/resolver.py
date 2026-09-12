from __future__ import annotations

import json
import hashlib
import os
import re
import stat
import subprocess
import tomllib
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
        *,
        probe_versions: bool = True,
    ) -> dict[str, object]:
        requested = kinds or ["node", "python", "go"]
        result: dict[str, object] = {}
        for raw_kind in requested:
            kind = raw_kind.strip().lower()
            if kind in {"node", "python", "go"}:
                result[kind] = self._discover_kind(kind, probe_versions=probe_versions)
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
            kind: self._discover_kind(kind, probe_versions=False)
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
            payload = self._discover_kind(kind, probe_versions=False)
            selected = payload.get("selected")
            if isinstance(selected, dict):
                executables = selected.get("executables")
                if isinstance(executables, dict):
                    candidate = executables.get(raw)
                    if isinstance(candidate, str) and self._validated_executable(Path(candidate)):
                        return candidate

        found = self._query_program(raw)
        return str(found) if found is not None else None

    def project_context(
        self,
        program: str,
        cwd: Path | None = None,
    ) -> dict[str, object]:
        """Return project-owned version/tool requirements without executing tools.

        The context is deliberately metadata-only.  It never inspects version-manager
        installation directories and never runs nvm/asdf/mise/go/node/python.  The
        fingerprint is used to invalidate Host-resolution cache entries when project
        version files change.
        """

        raw_program = program.strip().lower()
        kind = _PROGRAM_KINDS.get(raw_program, "")
        directory = self._project_directory(cwd)
        identity_directory = directory
        requirements: list[dict[str, str]] = []

        if kind == "node":
            version_file = self._nearest_named_file(directory, (".nvmrc", ".node-version"))
            if version_file is not None:
                value = self._read_first_line(version_file)
                if value:
                    requirements.append(self._requirement(version_file, "runtime_version", value))
            node_engine_found = False
            package_manager_found = False
            node_manifests = self._node_package_manifests(directory)
            if directory == self.workspace and len(node_manifests) == 1:
                identity_directory = node_manifests[0].parent
            for package_json in node_manifests:
                try:
                    payload = json.loads(package_json.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                engines = payload.get("engines")
                node_requirement = engines.get("node") if isinstance(engines, dict) else None
                if not node_engine_found and isinstance(node_requirement, str) and node_requirement.strip():
                    requirements.append(self._requirement(
                        package_json,
                        "node_engine",
                        node_requirement.strip(),
                    ))
                    node_engine_found = True
                package_manager = payload.get("packageManager")
                if not package_manager_found and isinstance(package_manager, str) and package_manager.strip():
                    requirements.append(self._requirement(
                        package_json,
                        "package_manager",
                        package_manager.strip(),
                    ))
                    package_manager_found = True
                if node_engine_found and package_manager_found:
                    break
        elif kind == "python":
            virtual_environment = self._python_virtual_environment(directory)
            if virtual_environment is not None:
                try:
                    value = str(virtual_environment.relative_to(self.workspace))
                except ValueError:
                    value = virtual_environment.name
                requirements.append(self._requirement(
                    virtual_environment / "pyvenv.cfg",
                    "python_virtual_environment",
                    value,
                ))
            version_file = self._nearest_file(directory, ".python-version")
            if version_file is not None:
                value = self._read_first_line(version_file)
                if value:
                    requirements.append(self._requirement(version_file, "runtime_version", value))
            for ancestor in self._project_ancestors(directory):
                pyproject = ancestor / "pyproject.toml"
                if not pyproject.is_file():
                    continue
                try:
                    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                except (OSError, tomllib.TOMLDecodeError):
                    payload = {}
                project = payload.get("project") if isinstance(payload, dict) else None
                requires_python = project.get("requires-python") if isinstance(project, dict) else None
                if isinstance(requires_python, str) and requires_python.strip():
                    requirements.append(self._requirement(
                        pyproject,
                        "python_requires",
                        requires_python.strip(),
                    ))
                    break
        elif kind == "go":
            version_file = self._nearest_file(directory, ".go-version")
            if version_file is not None:
                value = self._read_first_line(version_file)
                if value:
                    requirements.append(self._requirement(version_file, "runtime_version", value))
            go_mod = self._nearest_file(directory, "go.mod")
            if go_mod is not None:
                try:
                    lines = go_mod.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("go "):
                        requirements.append(self._requirement(
                            go_mod,
                            "go_version",
                            stripped.split(None, 1)[1].strip(),
                        ))
                    elif stripped.startswith("toolchain "):
                        requirements.append(self._requirement(
                            go_mod,
                            "go_toolchain",
                            stripped.split(None, 1)[1].strip(),
                        ))

        try:
            relative_cwd = str(identity_directory.relative_to(self.workspace)) or "."
        except ValueError:
            relative_cwd = "."
        identity = {
            "program": raw_program,
            "kind": kind,
            "cwd": relative_cwd,
            "requirements": requirements,
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {**identity, "fingerprint": digest}

    def _project_directory(self, cwd: Path | None) -> Path:
        directory = (cwd or self.workspace).resolve()
        if directory != self.workspace and not _within(directory, self.workspace):
            return self.workspace
        return directory if directory.is_dir() else directory.parent

    def _nearest_named_file(self, directory: Path, names: tuple[str, ...]) -> Path | None:
        for ancestor in self._project_ancestors(directory):
            for name in names:
                candidate = ancestor / name
                if candidate.is_file():
                    return candidate
        return None

    def _nearest_file(self, directory: Path, name: str) -> Path | None:
        return self._nearest_named_file(directory, (name,))

    def _python_virtual_environment(self, directory: Path) -> Path | None:
        for ancestor in self._project_ancestors(directory):
            candidates: list[Path] = []
            try:
                entries = list(ancestor.iterdir())[:256]
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_symlink() or not entry.is_dir():
                        continue
                    if not (entry / "pyvenv.cfg").is_file():
                        continue
                    entry.resolve(strict=True).relative_to(self.workspace)
                except (OSError, ValueError):
                    continue
                candidates.append(entry)
            if candidates:
                candidates.sort(
                    key=lambda item: (
                        0 if item.name == ".venv" else 1 if item.name == "venv" else 2,
                        item.name.casefold(),
                    )
                )
                return candidates[0]
        return None

    def _project_ancestors(self, directory: Path) -> list[Path]:
        result: list[Path] = []
        current = directory
        while True:
            result.append(current)
            if current == self.workspace:
                break
            parent = current.parent
            if parent == current or not _within(parent, self.workspace):
                break
            current = parent
        return result

    def _node_package_manifests(self, directory: Path) -> list[Path]:
        """Return nearby Node manifests without scanning outside the workspace.

        Commands inside a JS package use ancestor metadata. Workspace-level
        discovery additionally performs a bounded depth-two scan so repositories
        whose root is not a Node project can still expose an embedded web package.
        """
        manifests = [
            ancestor / "package.json"
            for ancestor in self._project_ancestors(directory)
            if (ancestor / "package.json").is_file()
        ]
        if manifests or directory != self.workspace:
            return manifests

        ignored = {".git", ".venv", "node_modules", "dist", "build", "vendor"}
        queue: list[tuple[Path, int]] = [(self.workspace, 0)]
        visited = 0
        discovered: list[Path] = []
        while queue and visited < 512:
            current, depth = queue.pop(0)
            visited += 1
            try:
                entries = sorted(
                    current.iterdir(),
                    key=lambda item: item.name.casefold(),
                )[:256]
            except OSError:
                continue
            for entry in entries:
                if entry.name in ignored or entry.name.startswith("."):
                    continue
                try:
                    if entry.is_symlink() or not entry.is_dir():
                        continue
                    entry.resolve(strict=True).relative_to(self.workspace)
                except (OSError, ValueError):
                    continue
                package_json = entry / "package.json"
                if package_json.is_file():
                    discovered.append(package_json)
                if depth < 1:
                    queue.append((entry, depth + 1))
        return discovered

    def _requirement(self, path: Path, requirement_type: str, value: str) -> dict[str, str]:
        try:
            source = str(path.relative_to(self.workspace))
        except ValueError:
            source = path.name
        return {"source": source, "type": requirement_type, "value": value}

    @staticmethod
    def _read_first_line(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except (OSError, IndexError):
            return ""

    def _discover_kind(self, kind: str, *, probe_versions: bool = True) -> dict[str, object]:
        cache_key = kind
        if probe_versions:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        hint = self._workspace_hint(kind)
        candidates = self._candidates(kind, probe_versions=probe_versions)
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
        if probe_versions:
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

    def _candidates(self, kind: str, *, probe_versions: bool = True) -> list[ToolchainCandidate]:
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
            kind, paths, executable_names, probe_versions=probe_versions,
        )

    def _build_candidates(
        self,
        kind: str,
        paths: list[tuple[Path, str, Path]],
        executable_names: list[str],
        *,
        probe_versions: bool = True,
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
            version = self._read_version(kind, resolved, bin_dir) if probe_versions else ""
            if probe_versions and not version:
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
