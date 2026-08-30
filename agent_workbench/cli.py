from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from .config import DEFAULT_HOST, DEFAULT_PORT, LaunchConfig, load_env_file
from .launcher import MCPLauncher
from .network import create_network_provider


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动 MicroMatrix Workbench Agent Runtime，并通过配置的 Network Provider 提供公网 MCP 地址"
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="MCP workspace，默认使用当前目录",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"MCP 本地监听地址，默认: {DEFAULT_HOST}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"MCP 本地监听端口，默认: {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"OAuth / Network Provider 配置文件，默认: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="校验 Workspace 与基础部署配置后退出，不启动 Runtime/Tunnel",
    )
    return parser.parse_args()


def _run() -> int:
    args = parse_args()
    env = load_env_file(args.env_file.expanduser().resolve())
    config = LaunchConfig.from_env(
        workspace=Path(args.workspace),
        env=env,
        host=args.host,
        port=args.port,
    )
    if args.check_config:
        provider = create_network_provider(config.network.provider, lambda _message: None)
        provider.validate_config(config.network)
        print(
            "配置检查通过: "
            f"workspace={config.workspace}, provider={config.network.provider}, "
            f"listen={config.host}:{config.port}, lifecycle={config.lifecycle}"
        )
        return 0
    launcher = MCPLauncher(log=print)

    def shutdown(_signum: int, _frame: object) -> None:
        print("\n正在关闭服务...")
        launcher.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        info = launcher.start(config)
        print()
        print("=" * 70)
        print("Agent Runtime 已启动")
        print("=" * 70)
        print(f"Workspace : {info.workspace}")
        print(f"Local MCP : {info.local_mcp_url}")
        print(f"Network   : {info.url_mode}")
        print(f"Public URL: {info.public_base_url}")
        print(f"Public MCP: {info.public_mcp_url}")
        print(f"OAuth URL : {info.public_base_url}")
        print()
        print("OpenAI MCP Server 地址:")
        print(f"  {info.public_mcp_url}")
        print()
        print("按 Ctrl+C 停止服务。")
        print("=" * 70)
        launcher.wait()
        return 1 if launcher.exit_reason else 0
    finally:
        launcher.stop()


def main() -> int:
    try:
        return _run()
    except KeyboardInterrupt:
        print("\n正在退出...", file=sys.stderr)
        return 130
    except Exception as exc:  # CLI boundary: report expected startup failures cleanly.
        print(f"\n启动失败:\n  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
