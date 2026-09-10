from __future__ import annotations

import base64
import json
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_workbench.host_execution import (
    HostExecutionError,
    HostExecutionRequest,
    HostProcessHandle,
    HostProcessSupervisor,
)

from .base import HostCapabilityDescriptor, HostCapabilityError
from .browser_resolution import BrowserApplication, resolve_chromium_browser


def _websocket_connection(url: str):
    try:
        from websocket import create_connection
    except ImportError as exc:
        raise HostCapabilityError(
            "Browser Host 缺少 websocket-client 依赖，请重新安装/打包 Desktop 依赖。"
        ) from exc
    return create_connection(url, timeout=8, suppress_origin=True)


class _CDPConnection:
    def __init__(self, url: str) -> None:
        self._socket = _websocket_connection(url)
        self._lock = threading.RLock()
        self._sequence = 0

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            command_id = self._sequence
            self._socket.send(json.dumps({
                "id": command_id,
                "method": method,
                "params": dict(params or {}),
            }))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                raw = self._socket.recv()
                if not raw:
                    continue
                payload = json.loads(raw)
                if payload.get("id") != command_id:
                    continue
                if isinstance(payload.get("error"), dict):
                    message = str(payload["error"].get("message") or "CDP command failed")
                    raise HostCapabilityError(message)
                result = payload.get("result")
                return dict(result) if isinstance(result, dict) else {}
            raise HostCapabilityError(f"CDP command 超时: {method}")

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            pass


@dataclass(slots=True)
class _BrowserSession:
    session_id: str
    server_id: str
    generation: str
    process: HostProcessHandle
    profile: Path
    port: int
    bundle_id: str
    cdp: _CDPConnection
    headless: bool
    last_observation_id: str = ""
    lock: threading.RLock = field(default_factory=threading.RLock)


def _http_json(port: int, path: str, *, method: str = "GET") -> Any:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        headers={"Connection": "close"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_devtools(profile: Path, process: HostProcessHandle, timeout: float) -> tuple[int, str]:
    marker = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HostCapabilityError("浏览器在 CDP 就绪前退出。")
        try:
            lines = marker.read_text(encoding="utf-8").splitlines()
        except OSError:
            time.sleep(0.05)
            continue
        if lines and lines[0].strip().isdigit():
            return int(lines[0].strip()), lines[1].strip() if len(lines) > 1 else ""
        time.sleep(0.05)
    raise HostCapabilityError("等待浏览器 CDP 端口超时；默认浏览器可能不支持 Chromium CDP。")


def _page_websocket(port: int) -> str:
    targets = _http_json(port, "/json/list")
    if isinstance(targets, list):
        for target in targets:
            if isinstance(target, dict) and target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
    created = _http_json(port, "/json/new?about%3Ablank", method="PUT")
    if isinstance(created, dict) and created.get("webSocketDebuggerUrl"):
        return str(created["webSocketDebuggerUrl"])
    raise HostCapabilityError("浏览器没有可用的 CDP Page Target。")


def _target_expression(ref: str, selector: str, observation_id: str = "") -> str:
    if ref:
        if not observation_id:
            raise HostCapabilityError(
                "使用 Browser ref 时必须提供对应的 observation_id。",
                code="STALE_BROWSER_REFERENCE",
                stage="validation",
            )
        target_selector = (
            f'[data-mmx-ref="{ref}"][data-mmx-observation="{observation_id}"]'
        )
        return f"document.querySelector({json.dumps(target_selector)})"
    if selector:
        return f"document.querySelector({json.dumps(selector)})"
    raise HostCapabilityError(
        "需要 ref 或 selector。",
        code="INVALID_BROWSER_TARGET",
        stage="validation",
    )


class BrowserHostCapability:
    descriptor = HostCapabilityDescriptor(
        name="browser",
        provider="desktop_chromium_cdp",
        session_based=True,
        operations=("open", "navigate", "snapshot", "click", "fill", "press", "screenshot", "status", "close"),
    )

    def __init__(self, process_supervisor: HostProcessSupervisor, *, generation: str = "") -> None:
        self._processes = process_supervisor
        self._generation = generation or "standalone"
        self._generation_prefix = self._generation[:10]
        self._sessions: dict[str, _BrowserSession] = {}
        self._lock = threading.RLock()

    def invoke(
        self,
        action: str,
        *,
        server_id: str,
        session_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "open":
            result = self._open(server_id, parameters)
            session = self._session(server_id, str(result["session_id"]))
            return self._with_post_observation(session, result, parameters)
        if action == "close":
            with self._lock:
                existing = self._sessions.get(session_id)
            if existing is None:
                if session_id.startswith("br_") and not session_id.startswith(
                    f"br_{self._generation_prefix}_"
                ):
                    raise HostCapabilityError(
                        "Browser Session 属于已失效的 Host generation。",
                        code="SESSION_EXPIRED",
                        stage="session",
                    )
                return {"closed": False, "session_id": session_id}
            if existing.server_id != server_id:
                raise HostCapabilityError("Browser Session 不存在或不属于当前 MCP Server。")
            self._close_session(existing)
            return {"closed": True, "session_id": session_id}
        session = self._session(server_id, session_id)
        with session.lock:
            if action == "navigate":
                result = self._navigate(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "snapshot":
                return self._snapshot(session, parameters)
            if action == "click":
                result = self._click(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "fill":
                result = self._fill(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "press":
                result = self._press(session, parameters)
                return self._with_post_observation(session, result, parameters)
            if action == "screenshot":
                return self._screenshot(session, parameters)
            if action == "status":
                return self._status(session)
        raise HostCapabilityError(f"不支持 Browser action: {action}")

    def _with_post_observation(
        self,
        session: _BrowserSession,
        action_result: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        result = {**action_result, "action_state": "completed"}
        if not bool(parameters.get("observe_after", True)):
            result["observation_state"] = "skipped"
            return result
        try:
            observation = self._snapshot(
                session,
                {
                    "max_text": int(parameters.get("max_text", 12_000)),
                    "max_elements": int(parameters.get("max_elements", 300)),
                },
            )
        except HostCapabilityError as exc:
            result.update(
                {
                    "observation_state": "failed",
                    "observation_error": {
                        "code": exc.code,
                        "stage": exc.stage,
                        "message": str(exc),
                    },
                }
            )
            return result
        result.update(
            {
                "observation_state": "succeeded",
                "observation": observation,
            }
        )
        return result

    def _open(self, server_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        application: BrowserApplication = resolve_chromium_browser()
        executable = application.executable
        bundle_id = application.identity
        headless = bool(parameters.get("headless", True))
        width = max(320, min(int(parameters.get("width", 1440)), 3840))
        height = max(240, min(int(parameters.get("height", 900)), 2160))
        url = self._validated_url(str(parameters.get("url") or "about:blank"))
        execution = self._processes.prepare(server_id)
        profile = execution.root / "profile"
        try:
            profile.mkdir(mode=0o700)
        except OSError as exc:
            self._processes.discard(execution)
            raise HostCapabilityError("无法创建 Host Capability Session 数据目录。") from exc
        argv = [
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-component-update",
            "--disable-background-networking",
            "--password-store=basic",
            "--remote-allow-origins=*",
            f"--window-size={width},{height}",
        ]
        if sys.platform == "darwin":
            argv.append("--use-mock-keychain")
        if headless:
            argv.append("--headless=new")
        argv.append(url)
        try:
            process = self._processes.launch(
                execution,
                HostExecutionRequest(
                    executable=executable,
                    argv=tuple(argv),
                ),
            )
        except HostExecutionError as exc:
            raise HostCapabilityError(
                str(exc),
                code="BROWSER_SPAWN_FAILED",
                stage="spawn",
            ) from exc
        try:
            port, _browser_ws = _wait_devtools(profile, process, 12)
            page_ws = _page_websocket(port)
            cdp = _CDPConnection(page_ws)
            cdp.command("Page.enable")
            cdp.command("Runtime.enable")
        except Exception as exc:
            diagnostics = self._processes.diagnostics(process)
            self._processes.release(process)
            detail = self._diagnostic_message(diagnostics)
            raise HostCapabilityError(
                f"{exc}{detail}",
                code="CDP_CONNECT_FAILED",
                stage="cdp_connect",
            ) from exc
        session_id = f"br_{self._generation_prefix}_{secrets.token_urlsafe(18)}"
        session = _BrowserSession(
            session_id=session_id,
            server_id=server_id,
            generation=self._generation,
            process=process,
            profile=profile,
            port=port,
            bundle_id=bundle_id,
            cdp=cdp,
            headless=headless,
        )
        with self._lock:
            self._sessions[session_id] = session
        return {
            "session_id": session_id,
            "provider": self.descriptor.provider,
            "generation": self._generation,
            "application_id": bundle_id,
            "application_source": application.source,
            "headless": headless,
            "isolated_profile": True,
            "url": url,
        }

    def _session(self, server_id: str, session_id: str) -> _BrowserSession:
        if not session_id:
            raise HostCapabilityError("缺少 browser session_id。")
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.server_id != server_id:
            if session_id.startswith("br_") and not session_id.startswith(
                f"br_{self._generation_prefix}_"
            ):
                raise HostCapabilityError(
                    "Browser Session 属于已失效的 Host generation。",
                    code="SESSION_EXPIRED",
                    stage="session",
                )
            raise HostCapabilityError(
                "Browser Session 不存在或不属于当前 MCP Server。",
                code="SESSION_NOT_FOUND",
                stage="session",
            )
        if session.process.poll() is not None:
            diagnostics = self._processes.diagnostics(session.process)
            self._close_session(session)
            raise HostCapabilityError(
                "Browser Session 已退出。" + self._diagnostic_message(diagnostics)
            )
        return session

    @staticmethod
    def _diagnostic_message(diagnostics: dict[str, object]) -> str:
        parts: list[str] = []
        exit_code = diagnostics.get("exit_code")
        signal_name = str(diagnostics.get("signal") or "")
        elapsed_ms = diagnostics.get("elapsed_ms")
        if exit_code is not None:
            parts.append(f"exit_code={exit_code}")
        if signal_name:
            parts.append(f"signal={signal_name}")
        if elapsed_ms is not None:
            parts.append(f"elapsed_ms={elapsed_ms}")
        stderr_tail = str(diagnostics.get("stderr_tail") or "").strip()
        stdout_tail = str(diagnostics.get("stdout_tail") or "").strip()
        if stderr_tail:
            parts.append(f"stderr_tail={stderr_tail[-4000:]}")
        elif stdout_tail:
            parts.append(f"stdout_tail={stdout_tail[-4000:]}")
        return f" Host process diagnostics: {'; '.join(parts)}" if parts else ""

    @staticmethod
    def _validated_url(value: str) -> str:
        url = value.strip() or "about:blank"
        if url == "about:blank":
            return url
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise HostCapabilityError("Browser 仅允许 http/https URL 或 about:blank。")
        return url

    def _navigate(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        url = self._validated_url(str(parameters.get("url") or ""))
        session.cdp.command("Page.navigate", {"url": url})
        self._wait_ready(session)
        return {"session_id": session.session_id, "url": self._location(session)}

    def _wait_ready(self, session: _BrowserSession) -> None:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            result = session.cdp.command("Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            value = ((result.get("result") or {}).get("value")
                     if isinstance(result.get("result"), dict) else None)
            if value in {"interactive", "complete"}:
                return
            time.sleep(0.1)

    @staticmethod
    def _evaluate(session: _BrowserSession, expression: str) -> Any:
        result = session.cdp.command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote = result.get("result")
        return remote.get("value") if isinstance(remote, dict) else None

    def _location(self, session: _BrowserSession) -> str:
        return str(self._evaluate(session, "location.href") or "")

    def _snapshot(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        max_text = max(500, min(int(parameters.get("max_text", 12000)), 50_000))
        max_elements = max(1, min(int(parameters.get("max_elements", 300)), 1000))
        observation_id = secrets.token_urlsafe(12)
        encoded_observation_id = json.dumps(observation_id)
        expression = f"""(() => {{
          const visible = (el) => {{ const s=getComputedStyle(el); const r=el.getBoundingClientRect(); return s.visibility!=='hidden' && s.display!=='none' && r.width>0 && r.height>0; }};
          document.querySelectorAll('[data-mmx-ref]').forEach((el) => {{ el.removeAttribute('data-mmx-ref'); el.removeAttribute('data-mmx-observation'); }});
          let n=0;
          const nodes=[...document.querySelectorAll('a,button,input,textarea,select,summary,[role],[contenteditable=true]')]
            .filter(visible).slice(0,{max_elements}).map((el) => {{
              const ref='e'+(++n); const rect=el.getBoundingClientRect();
              el.setAttribute('data-mmx-ref', ref); el.setAttribute('data-mmx-observation', {encoded_observation_id});
              return {{ref, tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'', name:el.getAttribute('aria-label')||el.getAttribute('name')||'', text:(el.innerText||el.textContent||'').trim().slice(0,300), value:('value' in el ? String(el.value) : '').slice(0,300), type:el.getAttribute('type')||'', rect:{{x:rect.x,y:rect.y,width:rect.width,height:rect.height}}}};
            }});
          return {{url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,{max_text}),elements:nodes}};
        }})()"""
        value = self._evaluate(session, expression)
        if not isinstance(value, dict):
            raise HostCapabilityError(
                "无法生成 Browser Snapshot。",
                code="BROWSER_OBSERVATION_FAILED",
                stage="observation",
            )
        session.last_observation_id = observation_id
        screenshot = self._screenshot(session, {"full_page": False})
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            "observation_id": observation_id,
            **value,
            **{key: item for key, item in screenshot.items() if key != "session_id"},
        }

    def _click(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        ref = str(parameters.get("ref") or "").strip()
        selector = str(parameters.get("selector") or "").strip()
        observation_id = str(parameters.get("observation_id") or "").strip()
        if ref and observation_id != session.last_observation_id:
            raise HostCapabilityError(
                "Browser ref 已过期；请先重新 snapshot 并使用新的 observation_id。",
                code="STALE_BROWSER_REFERENCE",
                stage="validation",
            )
        target = _target_expression(ref, selector, observation_id)
        result = self._evaluate(session, f"""(() => {{ const el={target}; if(!el) return false; el.scrollIntoView({{block:'center'}}); el.click(); return true; }})()""")
        if result is not True:
            raise HostCapabilityError(
                "Browser click 目标不存在。",
                code="BROWSER_TARGET_NOT_FOUND",
                stage="action",
            )
        time.sleep(0.05)
        self._wait_ready(session)
        return {"session_id": session.session_id, "clicked": True, "url": self._location(session)}

    def _fill(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        ref = str(parameters.get("ref") or "").strip()
        selector = str(parameters.get("selector") or "").strip()
        value = str(parameters.get("value") or "")
        observation_id = str(parameters.get("observation_id") or "").strip()
        if ref and observation_id != session.last_observation_id:
            raise HostCapabilityError(
                "Browser ref 已过期；请先重新 snapshot 并使用新的 observation_id。",
                code="STALE_BROWSER_REFERENCE",
                stage="validation",
            )
        target = _target_expression(ref, selector, observation_id)
        encoded = json.dumps(value)
        result = self._evaluate(session, f"""(() => {{ const el={target}; if(!el) return false; el.focus(); if(el.isContentEditable) {{ el.textContent={encoded}; }} else {{ const proto=el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set; if(setter) setter.call(el,{encoded}); else el.value={encoded}; }} el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText',data:{encoded}}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }})()""")
        if result is not True:
            raise HostCapabilityError(
                "Browser fill 目标不存在。",
                code="BROWSER_TARGET_NOT_FOUND",
                stage="action",
            )
        return {"session_id": session.session_id, "filled": True}

    def _press(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        key = str(parameters.get("key") or "").strip()
        if not key:
            raise HostCapabilityError("Browser press 缺少 key。")
        ref = str(parameters.get("ref") or "").strip()
        selector = str(parameters.get("selector") or "").strip()
        if ref or selector:
            observation_id = str(parameters.get("observation_id") or "").strip()
            if ref and observation_id != session.last_observation_id:
                raise HostCapabilityError(
                    "Browser ref 已过期；请先重新 snapshot 并使用新的 observation_id。",
                    code="STALE_BROWSER_REFERENCE",
                    stage="validation",
                )
            target = _target_expression(ref, selector, observation_id)
            focused = self._evaluate(session, f"(() => {{ const el={target}; if(el) el.focus(); return !!el; }})()")
            if focused is not True:
                raise HostCapabilityError(
                    "Browser press 目标不存在。",
                    code="BROWSER_TARGET_NOT_FOUND",
                    stage="action",
                )
        key_codes = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "ArrowUp": 38, "ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39}
        code = key_codes.get(key, ord(key.upper()) if len(key) == 1 else 0)
        params = {"key": key, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}
        if len(key) == 1:
            params["text"] = key
        session.cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", **params})
        session.cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", **params})
        if key == "Enter":
            time.sleep(0.05)
            self._wait_ready(session)
        return {"session_id": session.session_id, "pressed": key}

    def _screenshot(self, session: _BrowserSession, parameters: dict[str, Any]) -> dict[str, Any]:
        full_page = bool(parameters.get("full_page", False))
        params: dict[str, Any] = {"format": "png", "fromSurface": True}
        if full_page:
            metrics = session.cdp.command("Page.getLayoutMetrics")
            size = metrics.get("contentSize") if isinstance(metrics.get("contentSize"), dict) else {}
            if size:
                params["clip"] = {
                    "x": 0, "y": 0,
                    "width": float(size.get("width", 1)),
                    "height": float(size.get("height", 1)),
                    "scale": 1,
                }
        result = session.cdp.command("Page.captureScreenshot", params)
        data = str(result.get("data") or "")
        try:
            raw = base64.b64decode(data, validate=True)
        except Exception as exc:
            raise HostCapabilityError("Browser screenshot 返回无效数据。") from exc
        width = int.from_bytes(raw[16:20], "big") if len(raw) >= 24 and raw.startswith(b"\x89PNG") else 0
        height = int.from_bytes(raw[20:24], "big") if len(raw) >= 24 and raw.startswith(b"\x89PNG") else 0
        viewport = self._evaluate(
            session,
            "({width:window.innerWidth,height:window.innerHeight,device_scale_factor:window.devicePixelRatio||1,scroll_x:window.scrollX,scroll_y:window.scrollY})",
        )
        return {
            "session_id": session.session_id,
            "mime_type": "image/png",
            "data_base64": data,
            "image": {"width": width, "height": height},
            "viewport": viewport if isinstance(viewport, dict) else {},
            "coordinate_space": "css_pixels",
        }

    @staticmethod
    def _status(session: _BrowserSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "alive": session.process.poll() is None,
            "provider": "desktop_chromium_cdp",
            "application_id": session.bundle_id,
            "headless": session.headless,
            "isolated_profile": True,
        }

    def _close_session(self, session: _BrowserSession) -> None:
        with self._lock:
            self._sessions.pop(session.session_id, None)
        try:
            session.cdp.command("Browser.close")
        except Exception:
            pass
        session.cdp.close()
        self._processes.release(session.process)

    def close_server(self, server_id: str) -> None:
        with self._lock:
            sessions = [item for item in self._sessions.values() if item.server_id == server_id]
        for session in sessions:
            self._close_session(session)

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self._close_session(session)
