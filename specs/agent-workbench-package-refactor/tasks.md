# Agent Workbench 包结构重构实施计划

## 执行规则

- 每完成一个任务即更新勾选状态。
- 每个领域迁移完成后先运行对应测试，不把失败累积到下一阶段。
- 当前工作树中的 MCP 管理页和单 Workspace UI 修改不回滚、不覆盖。
- 旧业务文件只有在新路径测试通过且调用方迁移完成后才能删除。

## 任务清单

- [x] 1. 建立重构安全网
  - 记录当前 `agent_workbench` 模块清单、公开导出和稳定命令入口。
  - 增加新子包无副作用导入测试、公开导出身份测试和 `DesktopAPI` 兼容转发测试。
  - 增加目录边界测试，防止业务实现重新散落到根目录。
  - 运行当前 Python 全量测试与前端测试，保存迁移前基线。
  - _Requirement: R-3, R-6, R-7_

- [x] 2. 迁移 core 与 network specs
  - 新建 `agent_workbench/core`，迁移 config、resources、settings、version。
  - 将 `network_specs.py` 迁移为 `network/specs.py`。
  - 轻量化 `network/__init__.py`，内部调用改用具体模块路径。
  - 更新 build/release 脚本和相关测试 import。
  - 验证 config、version、build、network provider 测试。
  - _Requirement: R-1, R-3, R-4, R-5, R-7_

- [x] 3. 迁移 runtime
  - 新建 `agent_workbench/runtime`，迁移 process utils、Permission Broker 和 MCP process。
  - 保留根 `mcp_worker.py` 稳定模块入口并改为薄转发。
  - 更新 network、launcher、gateway process 和 executable discovery 的依赖路径。
  - 验证 Permission Broker、Workflow approval、进程安全和 Worker 命令测试。
  - _Requirement: R-1, R-3, R-4, R-7_

- [x] 4. 迁移 OAuth
  - 新建 `agent_workbench/oauth`，迁移 persistence 与 client store。
  - 保持 settings 路径、issuer 哈希、registry 和 token-secret 位置不变。
  - 更新 Server、Gateway、Desktop API 和测试 import。
  - 验证旧 OAuth fixture、Client 查询/撤销和进程重启持久化测试。
  - _Requirement: R-1, R-3, R-5, R-7_

- [x] 5. 拆分并迁移 Server 领域
  - 新建 `servers/models.py` 与 `servers/store.py`，拆分原 `server_profiles.py`。
  - 迁移单 Workspace launcher 与 Server manager。
  - 更新 `agent_workbench.__init__` 公开导出到新实现。
  - 保持 `agent_workbench.__all__` 的 Server 公开对象指向新实现；未公开旧深层模块不保留 shim。
  - 验证 Server profile、manager、launcher、CLI preflight 和旧配置 round-trip。
  - _Requirement: R-1, R-2, R-3, R-5, R-7_

- [x] 6. 重组 Gateway 模型、存储与进程
  - 新建 `gateways/models.py`，集中纯配置、Member、LaunchInfo 和诊断 DTO。
  - 将 Gateway profile store 从领域模型中拆出。
  - 迁移 Gateway 子进程配置与进程控制。
  - 消除 profile、launcher、process 之间的反向类型依赖。
  - 验证 Gateway profile/store/process 与旧配置 round-trip。
  - _Requirement: R-1, R-2, R-4, R-5, R-7_

- [x] 7. 拆分 Gateway diagnostics 与 launcher
  - 将 HTTP JSON/Form、PKCE/OAuth、Runtime、Server Card 和 auth challenge 检查提取到 `gateways/diagnostics.py`。
  - 将启动/停止、single/multi 分支、Provider、watcher 和回滚保留在 `gateways/launcher.py`。
  - 迁移 Gateway manager 并更新依赖。
  - 保持固定/动态 URL 启动顺序、issuer 绑定时机和错误语义。
  - 验证 Gateway launcher/diagnostic/framework/manager 全部测试。
  - _Requirement: R-1, R-2, R-3, R-4, R-7_

- [x] 8. 拆分 Update 领域
  - 将原 `updates.py` 转换为 `updates` 包。
  - 提取 Release 查询、平台命名、代理、TLS 和版本比较到 `updates/release.py`。
  - 提取 checksum、安装目标和平台 helper 到 `updates/installer.py`。
  - 保留下载线程、状态机和安装编排于 `updates/manager.py`。
  - 通过 `updates/__init__.py` 保持既有公开导入语义。
  - 验证更新命名、重试、checksum、helper 和平台安装测试。
  - _Requirement: R-1, R-2, R-3, R-4, R-7_

- [x] 9. 拆分 DesktopAPI 与 Workbench manager
  - 新建 `api/base.py`、`approvals.py`、`workbench.py`、`services.py`、`oauth.py`、`update.py`。
  - 将 Workbench manager 迁移至 `api/workbench_manager.py`。
  - 在 `api/desktop.py` 组合保持原方法集合的 `DesktopAPI`。
  - 将根 `desktop_api.py` 收敛为仅重导出 `DesktopAPI` 的兼容层。
  - 更新测试 patch 到真实定义模块。
  - 验证 Desktop API、Workbench、权限审批和 UI bridge 测试。
  - _Requirement: R-1, R-2, R-3, R-4, R-5, R-7_

- [x] 10. 收敛入口与删除旧实现
  - 更新 CLI、Desktop、Worker、构建脚本和包 `__init__` 使用新路径。
  - 删除已无调用方的根目录业务实现，只保留稳定入口和必要兼容层。
  - 全仓扫描旧 import、旧 patch 路径与过期文档路径。
  - 验证根目录边界和全部模块 import smoke。
  - _Requirement: R-1, R-3, R-4, R-7_

- [x] 11. 更新架构与开发文档
  - 补充最终目录树、依赖方向、公开入口和兼容策略。
  - 更新涉及旧模块路径的开发、构建与部署文档。
  - 确认文档不声称不存在的兼容能力。
  - _Requirement: R-1, R-3, R-7_

- [x] 12. 完成最终回归与打包验证
  - 运行 `compileall` 和所有新子包 import smoke。
  - 运行 Python 全量测试并处理非平台限定失败。
  - 运行前端测试、规范检查、TypeScript/Vue typecheck 和 Vite build。
  - 运行 Server deployment 测试。
  - 更新 PyInstaller 收集参数并执行 onedir smoke build。
  - 验证桌面入口、Web 资源和内部 MCP Worker 均被正确打包。
  - _Requirement: R-3, R-5, R-6, R-7_

- [x] 13. 最终审计
  - 对照 requirements/design/tasks 检查最终实现。
  - 确认当前 UI 修改仍存在并通过测试。
  - 执行 `git diff --check`，列出变更、兼容说明和验证结果。
  - _Requirement: R-1, R-2, R-3, R-4, R-5, R-6, R-7_
