# Agent Workbench 包结构

本文记录 `agent_workbench` 重构后的最终领域边界、依赖方向、稳定入口与兼容策略。

## 1. 最终目录

```text
agent_workbench/
├── __init__.py                 # 稳定公开 Python 导出
├── __main__.py                 # python -m agent_workbench
├── cli.py                      # CLI 编排
├── desktop.py                  # pywebview 桌面入口
├── mcp_worker.py               # 内部 MCP Worker 稳定入口
├── desktop_api.py              # DesktopAPI 稳定兼容入口
├── api/
│   ├── desktop.py              # DesktopAPI Mixin Facade
│   ├── base.py                 # 生命周期、日志、设置、OS bridge
│   ├── approvals.py            # Permission/Workflow Approval
│   ├── workbench.py            # Workbench bridge
│   ├── workbench_manager.py    # Workbench Target/Capability 编排
│   ├── services.py             # Server/Gateway bridge
│   ├── oauth.py                # OAuth Client bridge
│   └── update.py               # Update bridge
├── core/
│   ├── config.py               # 核心启动/网络配置模型
│   ├── resources.py            # 资源与打包路径
│   ├── settings.py             # 用户设置存取
│   └── version.py              # 版本解析
├── runtime/
│   ├── mcp_process.py          # 内部 MCP 进程入口
│   ├── permission_broker.py    # Desktop Permission Broker
│   └── process.py              # 进程公共工具
├── servers/
│   ├── models.py               # Server Profile 模型
│   ├── store.py                # Server Profile 持久化
│   ├── launcher.py             # 单 Server 启动生命周期
│   └── manager.py              # 多 Server 管理
├── gateways/
│   ├── models.py               # Gateway/Profile/Diagnostic DTO
│   ├── store.py                # Gateway 持久化
│   ├── process.py              # Gateway 子进程控制
│   ├── diagnostics.py          # Runtime/OAuth/PKCE 公网诊断
│   ├── launcher.py             # Gateway 生命周期编排
│   └── manager.py              # 多 Gateway 管理
├── oauth/
│   ├── persistence.py          # OAuth issuer/secret 持久化
│   └── client_store.py         # OAuth Client Registry
├── updates/
│   ├── release.py              # Release 查询、版本、平台命名、代理
│   ├── installer.py            # checksum、安装目标、平台 helper
│   └── manager.py              # 下载状态机与安装编排
├── network/                    # Network Provider 领域
├── executables/                # 外部可执行程序发现与校验
└── web/                        # Vue/Vite 桌面前端
```

根目录只保留稳定入口和明确承诺的兼容入口：`__init__.py`、`__main__.py`、
`cli.py`、`desktop.py`、`mcp_worker.py` 与 `desktop_api.py`。其余重构前的内部
模块路径不再保留 shim；项目内部代码必须直接引用领域子包中的真实定义模块。

## 2. 依赖方向

依赖遵循由稳定基础层向编排层单向上升的原则：

```text
core
  ↑
runtime / oauth / network / executables
  ↑
servers / gateways / updates
  ↑
api
  ↑
desktop / cli / mcp_worker
```

- `core` 不依赖桌面 API、Manager 或 UI。
- `servers`、`gateways` 直接依赖 `core`、`runtime`、`oauth`、`network` 的具体稳定模块，避免通过重型包入口制造循环依赖。
- `api` 只做桌面 bridge 与跨领域编排，不承载底层持久化 schema。
- `web` 只通过 pywebview 暴露的 `DesktopAPI` 调用后端，不直接访问 Manager/Store。

## 3. DesktopAPI Facade

`agent_workbench.api.desktop.DesktopAPI` 由多个 Mixin 组合而成，并保持重构前的方法名、参数和返回结构：

```python
class DesktopAPI(
    ApprovalAPI,
    WorkbenchAPI,
    ServiceAPI,
    OAuthAPI,
    UpdateAPI,
    DesktopBaseAPI,
):
    pass
```

共享 Store、Manager、Permission Broker、日志、Window 与 Update 状态只在
`DesktopBaseAPI.__init__` 初始化。Mixin 之间通过 Facade 的共享上下文协作。

## 4. 稳定入口

以下入口继续保持：

- `python -m agent_workbench`
- `python -m agent_workbench.mcp_worker`
- `agent_workbench.desktop.main()`
- `agent_workbench.__all__` 中原有公开类型
- `agent_workbench.desktop_api.DesktopAPI`

项目内部代码应使用新领域路径，例如：

```python
from agent_workbench.core.config import LaunchConfig
from agent_workbench.servers.launcher import MCPLauncher
from agent_workbench.gateways.manager import MCPGatewayManager
from agent_workbench.api.desktop import DesktopAPI
from agent_workbench.updates.release import fetch_latest_release
```

## 5. 兼容策略

仅对明确列入稳定入口的旧路径提供兼容。目前根模块兼容面只包含
`agent_workbench.desktop_api.DesktopAPI`。兼容模块必须满足两个条件：

1. 只从新领域模块重导出对象，不复制业务实现；
2. 重导出的类或函数与新模块对象身份一致。

未通过 `agent_workbench.__all__` 导出、不是命令入口、也未写入持久化格式的旧
内部模块路径不承诺兼容。新代码和测试 monkeypatch 均应指向真实定义模块，
例如 Gateway 诊断中的 HTTP patch 应指向 `agent_workbench.gateways.diagnostics`。

## 6. 数据与安全边界

本次目录重构不迁移用户数据，也不改变以下语义：

- Server/Gateway Profile schema 与设置目录；
- OAuth issuer、Client Registry 与 token secret 持久化路径；
- Permission Broker 默认权限和 Workspace 边界；
- Network Provider 的公网暴露方式；
- Update checksum、平台安装和回滚流程；
- Workbench Skill、Workflow、Run 与 MCP Connection 资产位置。

目录移动不能作为改变这些协议或持久化格式的理由。

## 7. 开发约定

- 新业务实现放入对应领域子包，不再向 `agent_workbench` 根目录增加业务模块。
- 测试 patch 真实定义位置；只对明确保留的兼容模块做对象身份测试。
- 新子包 `__init__.py` 保持轻量，不在 import 时启动进程、网络请求或 UI。
- 修改 PyInstaller、CLI 或 Worker 时，优先引用新领域路径，同时保留既有命令入口。
