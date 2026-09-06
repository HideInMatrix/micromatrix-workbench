"""Desktop-confirmed toolchains. Registrations are data, never shell startup code."""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..sandbox.backend import create_process_sandbox

PROGRAMS = {"node", "npm", "npx", "pnpm", "yarn", "python", "python3", "pip", "pip3"}


def _root(value: str, *, resolve: bool = True) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("工具链目录必须是绝对路径。")
    path = path.resolve() if resolve else Path(os.path.abspath(path))
    home = Path.home().resolve()
    if path == Path(path.anchor) or path == home or path in home.parents:
        raise ValueError("不能把整个 Home 或其上级目录注册为工具链目录。")
    for name in (".ssh", ".aws", ".azure", ".gnupg", ".codex", ".config/gcloud"):
        secret = home / name
        if path == secret or secret in path.parents or path in secret.parents:
            raise ValueError("凭据目录不能注册为工具链目录。")
    return path


def normalize_registrations(values: Any) -> tuple[dict[str, Any], ...]:
    """Validate persisted shape without touching inactive profiles' installations."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("toolchains 必须是注册列表。")
    result = []
    seen = set()
    for raw in values:
        if not isinstance(raw, dict) or raw.get("program") not in PROGRAMS:
            raise ValueError("不支持的工具链程序。")
        program = raw["program"]
        if program in seen:
            raise ValueError(f"重复工具链注册: {program}")
        seen.add(program)
        executable = Path(str(raw.get("executable", ""))).expanduser()
        if not executable.is_absolute():
            raise ValueError("工具链程序必须是绝对路径。")
        roots = raw.get("read_roots")
        if not isinstance(roots, list) or not roots:
            raise ValueError("工具链缺少已确认的只读目录。")
        # Shape validation must not touch installations: stale records must remain editable.
        for root in roots:
            if str(_root(str(root), resolve=False)) != str(root):
                raise ValueError("工具链只读目录发生变化，请重新注册。")
        version = str(raw.get("version", ""))
        fingerprint = str(raw.get("fingerprint", ""))
        if not version or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("工具链尚未验证，请在桌面点击“验证并注册”。")
        runtime_target = str(raw.get("runtime_target", ""))
        runtime_fingerprint = str(raw.get("runtime_fingerprint", ""))
        if program in {"node", "python", "python3"}:
            if not Path(runtime_target).is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", runtime_fingerprint):
                raise ValueError("缺少实际解释器指纹，请重新验证并注册。")
        result.append({"runtime_target": runtime_target, "runtime_fingerprint": runtime_fingerprint,
                       "program": program, "executable": str(executable),
                       "read_roots": list(roots), "version": version,
                       "fingerprint": fingerprint})
    return tuple(result)


def fingerprint(executable: str, roots: list[str]) -> str:
    path = Path(executable)
    target = path.resolve(strict=True)
    if not target.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"工具链程序不可执行: {path}")
    if target.stat().st_mode & 0o002:
        raise ValueError("不能注册所有用户可写的程序。")
    digest = hashlib.sha256()
    digest.update(str(path).encode())
    digest.update(str(target).encode())
    for root in roots:
        resolved = _root(root)
        if str(resolved) != root or not resolved.is_dir():
            raise ValueError("工具链目录已变化或不存在，请重新注册。")
        digest.update(root.encode())
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_confinement(backend: Any) -> None:
    state = backend.state
    if not (state.enabled and state.filesystem_isolation and state.network_isolation):
        raise RuntimeError(
            "工具链执行需要完整 OS 文件和网络隔离；当前不可用，未启动程序。"
            f" {state.reason}"
        )


def toolchain_environment(path: list[str], home: Path, cache: Path, tmp: Path) -> dict[str, str]:
    # No inherited credentials, NODE_OPTIONS, PYTHONPATH or shell initialization.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}}
    env.update({"PATH": os.pathsep.join(path), "HOME": str(home), "USERPROFILE": str(home),
                "TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp),
                "XDG_CACHE_HOME": str(cache), "npm_config_cache": str(cache / "npm"),
                "YARN_CACHE_FOLDER": str(cache / "yarn"),
                "npm_config_store_dir": str(cache / "pnpm"),
                "PIP_CACHE_DIR": str(cache / "pip"), "UV_CACHE_DIR": str(cache / "uv"),
                "PYTHONPYCACHEPREFIX": str(cache / "pycache"),
                "COREPACK_HOME": str(cache / "corepack"), "PYTHONNOUSERSITE": "1"})
    return env


def probe_version(executable: str, backend: Any, cwd: Path, env: dict[str, str]) -> str:
    require_confinement(backend)
    command = backend.wrap([executable, "--version"], cwd=cwd)
    completed = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, timeout=8, shell=False)
    if completed.returncode:
        raise ValueError("工具链沙箱验证失败；请补充必要的只读依赖目录，不能关闭沙箱。 "
                         + completed.stderr[-1200:])
    version = completed.stdout.strip()
    if not version or len(version) > 512:
        raise ValueError("工具链未返回有效版本。")
    return version


def probe_runtime_target(program: str, executable: str, backend: Any,
                         cwd: Path, env: dict[str, str]) -> str:
    if program not in {"node", "python", "python3"}:
        return ""
    require_confinement(backend)
    args = (["-p", "process.execPath"] if program == "node" else
            ["-I", "-c", "import sys; print(sys._base_executable)"])
    completed = subprocess.run(backend.wrap([executable, *args], cwd=cwd),
                               cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, timeout=8, shell=False)
    target = completed.stdout.strip()
    if completed.returncode or not target or not Path(target).is_absolute():
        raise ValueError("无法在沙箱中确定实际解释器路径: " + completed.stderr[-1200:])
    return str(Path(target).resolve(strict=True))


def prepare_toolchain(program: str, executable: str, read_roots: list[str]) -> dict[str, Any]:
    """Inspect paths without executing them, so the user can review the scope."""
    if program not in PROGRAMS:
        raise ValueError("不支持的工具链程序。")
    path = Path(executable).expanduser()
    if not path.is_absolute():
        raise ValueError("请选择程序的绝对路径。")
    # Keep argv[0] (nvmd/asdf shims) and the venv path; validate real targets too.
    target = path.resolve(strict=True)
    inferred = [path.parent.parent if path.parent.name in {"bin", "Scripts"} else path.parent,
                target.parent.parent if target.parent.name in {"bin", "Scripts"} else target.parent]
    # Version managers also use directory symlinks (uv's cpython-3.x alias).
    # The kernel must traverse these links before it can reach the real binary.
    cursor = path
    for _ in range(16):
        for parent in cursor.parents:
            if (parent.is_symlink() and parent.is_relative_to(Path.home())
                    and parent.parent != Path.home()):
                inferred.append(parent.parent)
        if not cursor.is_symlink():
            break
        link = Path(os.readlink(cursor))
        cursor = link if link.is_absolute() else cursor.parent / link
    else:
        raise ValueError("工具链符号链接过深。")
    roots = sorted({str(_root(str(root))) for root in [*inferred, *read_roots]})
    fingerprint(str(path), roots)
    return {"program": program, "executable": str(path), "read_roots": roots}


def register_toolchain(program: str, executable: str, read_roots: list[str], *,
                       confirmed_roots: list[str] | None = None) -> dict[str, Any]:
    """Called only by the desktop confirmation button, not by an MCP tool."""
    prepared = prepare_toolchain(program, executable, read_roots)
    path = Path(prepared["executable"])
    roots = prepared["read_roots"]
    if confirmed_roots is not None and set(roots) != set(confirmed_roots):
        raise ValueError("检查后工具链目录发生变化，请重新检查并确认权限范围。")
    before = fingerprint(str(path), roots)
    from .resolver import ToolchainResolver
    with tempfile.TemporaryDirectory(prefix="toolchain-registration-") as temporary:
        runtime = Path(temporary).resolve()
        cache = runtime / "cache"
        cache.mkdir()
        backend = create_process_sandbox(
            mode="safe", workspace=runtime, runtime_dir=runtime,
            readable_roots=[*[Path(item) for item in roots], *system_read_roots()], writable_roots=[runtime],
            protected_paths=[Path(item) for item in roots], network=False,
        )
        env = toolchain_environment([str(path.parent), *ToolchainResolver.system_path_entries()],
                                    Path.home(), cache, runtime)
        version = probe_version(str(path), backend, runtime, env)
        runtime_target = probe_runtime_target(program, str(path), backend, runtime, env)
        runtime_fingerprint = fingerprint(runtime_target, roots) if runtime_target else ""
    if fingerprint(str(path), roots) != before:
        raise ValueError("验证期间工具链发生变化，请重新注册。")
    return {"program": program, "executable": str(path), "read_roots": roots,
            "version": version, "fingerprint": before,
            "runtime_target": runtime_target, "runtime_fingerprint": runtime_fingerprint}


def system_read_roots() -> list[Path]:
    import sys
    if sys.platform != "darwin":
        return []
    return [Path(value) for value in ("/System", "/Library", "/usr", "/bin", "/sbin",
                                      "/private/etc", "/private/var/db", "/private/var/select",
                                      "/opt/homebrew", "/usr/local")]


def write_launchers(registrations: tuple[dict[str, Any], ...], runtime_dir: Path) -> Path | None:
    """Exact shell aliases, preserving the original interpreter/shim argv[0]."""
    if not registrations or os.name == "nt":
        return None
    directory = runtime_dir / "toolchain-bin"
    directory.mkdir(mode=0o700)
    for item in registrations:
        launcher = directory / item["program"]
        launcher.write_text("#!/bin/sh\nexec " + shlex.quote(item["executable"]) + ' "$@"\n')
        launcher.chmod(0o500)
    return directory
