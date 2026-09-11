from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webview import Window

from .core.resources import web_ui_entrypoint
from .core.version import current_version
from .runtime.mcp_process import INTERNAL_MCP_FLAG, run_internal_mcp_server
from agent_runtime.sandbox.windows_launcher import (
    INTERNAL_WINDOWS_SANDBOX_FLAG,
    run_internal_windows_sandbox_process,
)


SUPPORTED_DESKTOP_PLATFORMS = frozenset({"darwin", "win32"})


def ensure_supported_desktop_platform(platform_name: str | None = None) -> None:
    current = (platform_name or sys.platform).lower()
    if current not in SUPPORTED_DESKTOP_PLATFORMS:
        raise RuntimeError(
            "MicroMatrix Workbench 桌面版当前仅支持 macOS 和 Windows；"
            "Linux 暂只支持无界面的 Server/CLI 部署。"
        )


def configure_titlebar(window: Window) -> None:
    """Keep the macOS title centered instead of the unified leading layout."""
    if sys.platform == "darwin":
        from AppKit import NSWindowToolbarStyleExpanded

        window.native.setToolbarStyle_(NSWindowToolbarStyleExpanded)


def main() -> int:
    if INTERNAL_WINDOWS_SANDBOX_FLAG in sys.argv:
        index = sys.argv.index(INTERNAL_WINDOWS_SANDBOX_FLAG)
        return run_internal_windows_sandbox_process(sys.argv[index + 1 :])

    if INTERNAL_MCP_FLAG in sys.argv:
        index = sys.argv.index(INTERNAL_MCP_FLAG)
        return run_internal_mcp_server(sys.argv[index + 1 :])

    ensure_supported_desktop_platform()

    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "桌面版需要 pywebview。开发环境请执行 pip install -r requirements-desktop.txt"
        ) from exc

    from .api.desktop import DesktopAPI

    entrypoint = web_ui_entrypoint()
    if not entrypoint.is_file():
        raise RuntimeError(
            "找不到桌面 Web UI 构建产物。请先在 agent_workbench/web 下执行 npm install && npm run build。"
        )

    app_version = current_version()
    api = DesktopAPI(app_version=app_version)
    window = webview.create_window(
        "MicroMatrix Workbench",
        str(entrypoint),
        js_api=api,
        width=1180,
        height=780,
        min_size=(960, 680),
        background_color="#fdfdfd",
    )
    api._bind_window(window)
    window.events.before_show += configure_titlebar
    window.events.closing += api._close
    webview.start(http_server=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
