from __future__ import annotations

from pathlib import Path

from ..core.config import NetworkConfig
from ..runtime.process import LogCallback
from .base import NetworkProviderResult
from .process import ProcessNetworkProvider


class FrpProvider(ProcessNetworkProvider):
    key = "frp"
    display_name = "FRP"
    process_name = "frpc"

    def __init__(self, log: LogCallback):
        super().__init__(log)

    def validate_config(self, config: NetworkConfig) -> None:
        validated = config.validated()
        if not validated.public_url:
            raise ValueError("FRP 模式必须填写最终对外访问的 Public URL。")
        raw_config = validated.options.get("config_file", "").strip()
        if not raw_config:
            raise ValueError("FRP 模式需要填写 frpc 配置文件路径。")
        config_file = Path(raw_config).expanduser().resolve()
        if not config_file.is_file():
            raise ValueError(f"FRP 配置文件不存在: {config_file}")

    def start(self, host: str, port: int, config: NetworkConfig) -> NetworkProviderResult:
        config = config.validated()
        self.validate_config(config)
        executable = self.resolve_executable(config.options.get("executable", ""), "frpc")
        raw_config = config.options.get("config_file", "").strip()
        config_file = Path(raw_config).expanduser().resolve()
        self._log(f"FRP Public URL: {config.public_url}")
        self._log(f"frpc 配置应将公网入口转发到 http://{host}:{port}")
        self.spawn([str(executable), "-c", str(config_file)], prefix="frpc")
        self.wait_until_stable()
        return NetworkProviderResult(self.key, config.public_url, "FRP")
