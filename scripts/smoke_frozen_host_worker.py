#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.local_permission_broker import (  # noqa: E402
    BROKER_VERSION,
    HOST_CAPABILITY_KIND,
    HOST_DIAGNOSTICS_FILE,
    atomic_json_write,
    sign_payload,
    verify_payload,
)


APP_NAME = "MicroMatrix Workbench"
SMOKE_TIMEOUT_SECONDS = 15.0


def frozen_executable(*, system: str | None = None) -> Path:
    current = (system or platform.system()).strip().lower()
    if current == "darwin":
        return ROOT / "dist" / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    if current == "windows":
        return ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
    raise RuntimeError(f"Desktop frozen Host smoke only supports macOS/Windows: {current}")


def _wait_for_file(path: Path, process: subprocess.Popen[bytes], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.05)
    return path.is_file()


def _stop_worker(process: subprocess.Popen[bytes], stop_file: Path) -> None:
    stop_file.touch(exist_ok=True)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def run_smoke(*, timeout: float = SMOKE_TIMEOUT_SECONDS) -> None:
    executable = frozen_executable()
    if not executable.is_file():
        raise RuntimeError(f"Frozen desktop executable not found: {executable}")

    secret = secrets.token_bytes(32)
    generation = f"package-smoke-{secrets.token_urlsafe(8)}"
    with tempfile.TemporaryDirectory(prefix="micromatrix-frozen-host-smoke-") as raw_directory:
        directory = Path(raw_directory)
        stop_file = directory / "stop"
        command = [
            str(executable),
            "--host-worker",
            "--directory",
            str(directory),
            "--secret",
            secret.hex(),
            "--host-instance-id",
            "package-smoke",
            "--generation",
            generation,
            "--generation-index",
            "1",
            "--stop-file",
            str(stop_file),
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            diagnostics_path = directory / HOST_DIAGNOSTICS_FILE
            if not _wait_for_file(diagnostics_path, process, timeout):
                stdout, stderr = process.communicate(timeout=2)
                raise RuntimeError(
                    "Frozen Host Worker did not publish diagnostics. "
                    f"exit={process.returncode} stdout={stdout[-1000:]!r} stderr={stderr[-2000:]!r}"
                )

            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            if not verify_payload(secret, diagnostics):
                raise RuntimeError("Frozen Host Worker diagnostics signature is invalid.")
            providers = {
                str(item.get("name") or "")
                for item in diagnostics.get("providers", [])
                if isinstance(item, dict)
            }
            required = {"browser", "desktop"}
            if not required.issubset(providers):
                raise RuntimeError(
                    f"Frozen Host Worker provider catalog is incomplete: {sorted(providers)}"
                )

            request_id = secrets.token_urlsafe(18)
            now = int(time.time())
            queued_at_ms = int(time.time() * 1000)
            payload: dict[str, object] = {
                "version": BROKER_VERSION,
                "kind": HOST_CAPABILITY_KIND,
                "request_id": request_id,
                "server_id": "package-smoke-server",
                "capability": "desktop",
                "action": "targets",
                "session_id": "",
                "generation": generation,
                "runtime_instance_id": "package-smoke-runtime",
                "queued_at_ms": queued_at_ms,
                "deadline_at_ms": queued_at_ms + int(timeout * 1000),
                "parameters": {
                    "_principal_hash": "package-smoke-principal",
                    "max_results": 3,
                },
                "created_at": now,
                "expires_at": now + max(1, int(timeout)),
                "pid": os.getpid(),
            }
            payload["signature"] = sign_payload(secret, payload)
            request_path = directory / f"{request_id}.host-capability.request.json"
            response_path = directory / f"{request_id}.host-capability.response.json"
            atomic_json_write(request_path, payload)
            if not _wait_for_file(response_path, process, timeout):
                raise RuntimeError("Frozen Desktop provider request did not produce a response.")
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if not verify_payload(secret, response):
                raise RuntimeError("Frozen Desktop provider response signature is invalid.")
            if response.get("ok") is not True:
                cause_code = str(response.get("cause_code") or "")
                # Headless CI and command runners may not own a WindowServer
                # session. That is an expected platform environment boundary;
                # reaching the native Desktop provider and failing closed is
                # still a valid packaging smoke.
                allowed_environment_errors = {
                    "DESKTOP_WINDOW_SERVER_UNAVAILABLE",
                    "DESKTOP_SCREEN_PERMISSION_REQUIRED",
                }
                if cause_code not in allowed_environment_errors:
                    raise RuntimeError(
                        "Frozen Desktop provider request failed unexpectedly: "
                        f"{cause_code}: {response.get('error')}"
                    )
                print(f"Desktop provider reached; environment gate: {cause_code}")
            else:
                result = response.get("result")
                target_count = len(result.get("targets", [])) if isinstance(result, dict) else 0
                print(f"Desktop provider reached; targets={target_count}")
            print(f"Frozen Host providers: {', '.join(sorted(providers))}")
        finally:
            _stop_worker(process, stop_file)
        if process.returncode != 0:
            raise RuntimeError(f"Frozen Host Worker did not stop cleanly: {process.returncode}")


def main() -> int:
    run_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
