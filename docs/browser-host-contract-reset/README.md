# Workbench 浏览器观察与 Desktop Host 整改计划

**文档状态：历史 Browser/Host 整改计划，源码实施记录见 [tasks.md](tasks.md)。**

2026-09-11 范围更新：用户明确 0.4.x 必须支持浏览器、Blender、Figma 等桌面应用的观察与操作。下文“通用桌面后端后续实现”的原范围决定已被 [0.4.x 通用桌面 Computer Use 计划](../desktop-computer-use-04/README.md) 取代；原有 Host 和工具契约整改继续复用。历史故障统计针对 a80e72f，不表示当前 071e2fa 仍存在全部问题。

- 制定日期：2026-09-10。
- 审查基线：`a80e72f`（fix: 二类模型使用问题）。
- 现场输入：用户汇总的 DB-015A / DB-015B 使用问题；现场故障尚未在本轮逐项重演。
- 目标：AI 通过 Workbench 看见当前界面，直接调用动作，再看见结果；Host 故障不拖垮 Runtime，恢复不要求重启整个项目。
- 约束：不增加旧工具别名、双协议 fallback、临时 Workflow 绕行或新旧模型兼容分发。

## 1. 阅读入口

| 文档 | 内容 |
| --- | --- |
| [requirements.md](requirements.md) | 范围、17 条验收要求、恢复语义 |
| [design.md](design.md) | 工具模型、进程边界、状态、授权、图像与结果契约 |
| [tasks.md](tasks.md) | 可勾选实施清单与故障测试矩阵 |
| 本文 | 分阶段详细执行计划、问题对应、改动边界与发布规则 |

## 2. 最终架构决策

### 2.1 保留什么

1. 保留 Runtime / Host 两类执行边界，CDP 继续实现浏览器控制。
2. 保留工具注册指纹、工作区边界、OS sandbox、签名 IPC 的身份校验原则。
3. 复用已有 `_image` / `make_tool_result` 图像输出通道。
4. 保留用户自行添加外部 MCP 的能力；它与内置 Browser 不混成一套产品专用适配。

### 2.2 改成什么

1. **一份公共工具注册表**：tools/list、Catalog、调用校验、工作流消费来自同一来源。
2. **Browser 原子工具公开**：使用已经存在的 browser_open、browser_snapshot 等名称，删除 browser_manage。无需对聚合入口维护权限并集和重复 schema。
3. **Runtime 本地执行闭环**：有效注册及允许路径内的命令执行不依赖 Host 实时解析。
4. **独立 Host 控制面和执行面**：Supervisor 管连接、调度、诊断和恢复；独立 Worker 运行 CDP 与宿主能力。控制面不能运行会阻塞它自己的 Provider 调用。
5. **观察与动作闭环**：Browser 返回真正的 MCP 图片、必要页面信息和清晰的执行状态，AI 自己决定下一步。

### 2.3 这轮不做什么

- 不增加通用桌面后端、浏览器扩展或新的 Computer Use MCP 服务。
- 不建设通用插件装载平台、全局事件总线或任意系统进程操作 API。
- 不增加 ephemeral workflow 引擎来修复工具不可调用的问题。
- 不让普通 Runtime 命令在失败后自动转为 Host Identity 执行。
- 不以减少文件数量为目的合并权限、沙箱或资源所有权边界。

独立 Worker 是为满足“卡死可终止、恢复不重启 Runtime”所需的故障隔离，不是为了增加抽象层。

## 3. 已确认根因及待核对项

本轮执行了注册表到 Catalog 的直接检查，发现 **17 个 invocation 指向未公开工具**：

- Browser：open、navigate、snapshot、click、fill、press、screenshot、status、close 共 9 个。
- Git：blame、diff、log、show、status 共 5 个。
- Process：kill_command、read_output、write_stdin 共 3 个。

其他已确认源码事实：

- Catalog 默认将内置工具标记 available，未读取 Host 健康状态。
- configured 由 Broker 对象/方法存在推断。
- Host Capability 和工具解析由同一线程串行执行。
- 已注册命令在 Broker 存在时仍强制咨询 Host。
- browser_manage 采用统一权限并集，截图没有接上现有图片返回通道。
- Desktop 主进程拥有 Broker；正常关闭时停止 Runtime/Gateway。Broker 每次初始化产生新的目录和 secret。

需要部署复核：DB-015 实际构建版本、Host 超时所在阶段、操作系统拒绝的原始证据、遗留 Workflow 的确切清单。不得仅凭 exit_code=71 推断 sandbox 拒绝，不得按 `db015*` 通配符直接删除工作流。

## 4. 阶段 0：冻结基线与契约清单

**产出：可重复的当前行为证据、影响清单，不先改业务逻辑。**

实施步骤：

1. 导出当前公共 tools/list、Catalog invocation、ToolDefinition、前端 DTO 与工作流工具引用。
2. 添加实际不变量测试：每个 Catalog invocation 必须存在于当前公共工具表；固定参数加用户输入能满足该工具 schema。
3. 扫描仓库及指定资产目录的 browser_manage、隐藏 Git/Process 工具引用，产出待迁移清单。
4. 固定包含 Browser、Git、Process、Skills、Workflow、外部 MCP 的测试夹具。
5. 将 DB-015 故障报告按“已复现 / 源码支持 / 待部署确认”标记，避免扩大或遗漏根因。

涉及：`tests/test_tool_framework.py`、`tests/test_custom_mcp_server.py`、工作台相关测试、一次性契约审查脚本。

验收门槛：能稳定检测现有 17 个错误引用，能定位实际引用资产；正常技能/外部 MCP 的间接 invocation 不被误判为必须同名顶层工具。

## 5. 阶段 1：统一公开工具契约

**解决 P0：Catalog 与工具暴露不一致、Browser 权限并集。**

涉及：

- `agent_runtime/core/{tool,registry,dispatcher}.py`
- `agent_runtime/tools/browser/{definitions,handlers}.py`
- `agent_runtime/workbench/{effective_tools,capability_catalog,tool_references}.py`
- `agent_runtime/tools/workbench/handlers.py`
- `agent_runtime/runtime.py`、`agent_runtime/protocol.py`
- `agent_workbench/api/workbench_manager.py`、前端 Catalog DTO 与消费组件

实施步骤：

1. ToolRegistry 只登记正式可调用工具，公开描述与 handler 绑定只维护一次。
2. 正式公开现有 Browser 原子工具；移除 browser_manage 定义、分发和调用方。
3. 每个工具声明准确 input/output schema、execution_kind、能力、操作权限与 annotations。status 明确只读；截图显式保存才涉及工作区写入。
4. Git / Process 保持各自现有公共入口；其内部细粒度方法不再伪装成公共工具注册项。
5. Catalog 直接消费公共描述，不再从丢失暴露信息的中间列表猜 invocation。所有组合能力的入口均执行注册表校验。
6. Workflow 调用也经过公共契约入口，清除借内部 handler 绕过工具可调用边界的路径。
7. Catalog 静态 revision 只跟工具和资产定义变化；健康更新有独立时间或 health_revision。
8. 更新前端与工具说明，移除引导 AI 创建 Workflow 以调用隐藏 Browser 工具的文案。

验收门槛：17 个失配项全部消除；公共工具参数、注解和实际校验一致；直接 MCP 完成 Browser 调用，不生成任何诊断 Workflow。

## 6. 阶段 2：切断 Runtime 到 Host 的非必要依赖

**解决 P0：Host Tool Resolution 阻塞普通命令。此阶段先于进程拆分落地。**

涉及：`tools/process/handlers.py`、`toolchains/resolver.py`、注册与项目上下文缓存、工具发现相关测试。

实施步骤：

1. 将“执行已确认入口”与“发现新入口”分开。
2. 已注册工具在本地验证指纹、范围和项目约束后立即执行，不请求 Host 比较路径。
3. 没有注册时只在 Runtime 明确允许的 PATH 解析，保持原 sandbox 约束。
4. 缓存按项目上下文和文件身份校验，不让缓存变为额外授权。
5. 前述路径均不满足时，才调用 Host 发现并生成注册提案。
6. 项目版本或注册指纹改变时明确失败，不因 Host 离线偷偷改用另一版本。
7. 对发现和执行记录各自错误，Host 解析失败不能使已有合法入口失效。

验收门槛：Host 完全离线时，按名称运行已注册 Node/Git/Python 成功；名称与绝对路径的有效入口一致；失效注册、未知工具、版本冲突各有明确结果。

## 7. 阶段 3：建立独立 Host 生命周期与 fail-fast

**解决 P0：假在线状态、逐请求长超时、缺少恢复控制面。**

涉及：

- `agent_runtime/local_permission_broker.py`：Runtime HostConnection
- `agent_workbench/runtime/permission_broker.py`：拆出 Supervisor 与 Worker 职责
- `agent_workbench/host_execution/*`、`host_capabilities/*`、`host_identity/*`
- `agent_workbench/api/base.py`、Server/Gateway 启停管理、`desktop.py` 和打包脚本

实施步骤：

1. 将 Provider 执行放入独立 Worker，Supervisor 维护稳定控制端点和自有资源记录。
2. Runtime 只保留一个 HostConnection，集中处理状态、认证握手、generation、ack、截止时间和重连。
3. 所有 Host 请求统一 request_id、runtime_instance_id、profile/server_id、principal、generation、deadline；不能仅按 server_id 隔离多个客户端。
4. 删除旧串行 Provider 执行循环；控制面永不执行 LaunchServices/CDP 等潜在阻塞操作。
5. 建立 heartbeat 与 ack 独立时限；目标心跳 250 ms、失效阈值 750 ms，并以真实故障注入校验小于 1 秒的拒绝预算。
6. 连接状态与 Provider 状态分离。Supervisor 在线但 Provider 不响应时报告 degraded，不继续声称 ready。
7. 提供 host_status 和 host_reconnect；状态查询在 Worker 死亡时仍可读，重连只重新握手。
8. Worker crash 有界退避重启；反复失败熔断。新 Worker 握手成功后 Runtime 自动重新连接。
9. 删除旧连接实现，不保留“新接口失败则回到旧 JSON 轮询”的路径。协议版本不一致明确拒绝。

验收门槛：主动终止或挂起 Worker 后 Host 调用小于 1 秒失败；状态与诊断可用；Runtime 不重启；恢复后新 Browser session 成功。新鲜心跳之后立刻崩溃的竞态也必须覆盖。

边界：正常退出整个 Desktop 仍按原产品规则停止服务。Worker 恢复不等于整台桌面应用退出后的系统级常驻恢复，也不等于恢复旧浏览器页面。

## 8. 阶段 4：权限、错误分层与受控诊断

**解决 P1：授权假象、错误不透明、缺少诊断；补齐受控 Host 重启。**

涉及：`permissions/*`、`local_permission_broker.py`、Supervisor、`api/approvals.py`、前端 `App.vue` 与新的权限 composable。

实施步骤：

1. 基础调用顺序统一：schema → 身份/暴露/能力 → 可行性预检 → 授权 → 执行前复核 → 执行。
2. 分离 Browser 观察/控制、普通 Runtime 会话授权和 Host 管理权限。
3. safe/trusted/dangerous 模式的授予规则显式列出，不让新增权限枚举自动扩大“全部允许”。
4. 系统辅助功能等缺失权限与应用内审批分别展示；仅凭用户 granted 不宣称 OS 已允许。
5. host_diagnostics 返回当前 Workbench 管理范围内的 PID、版本、generation、heartbeat、队列/Provider 状态和最近 N 条脱敏错误；无任意 ps/log/launchctl 参数。
6. 定义稳定错误码：HOST_DISCONNECTED、HOST_ACK_TIMEOUT、HOST_PROTOCOL_MISMATCH、APP_RESOLUTION_FAILED、BROWSER_SPAWN_FAILED、CDP_CONNECT_FAILED、SESSION_EXPIRED、POLICY_DENIED、OS_SANDBOX_DENIED、USER_PERMISSION_REQUIRED。
7. 记录 request_id、stage、queued_at、host_ack_at、provider_start_at 与 cause_code；没有证据的字段为 null。
8. host_restart 只操作自有 Worker，列出受影响 Profile/session；管理授权独立于 Browser。不得允许任意 PID 或 bundle 参数。
9. 将权限轮询与响应从 App.vue 抽为 `usePermissionRequests`，展示组件消费状态，保持 composable。

验收门槛：Host 离线与 Provider 启动失败可区分；授权不扩大到其他能力；无效系统权限不进入无意义审批循环；日志不泄漏 broker secret、令牌或全局环境。

## 9. 阶段 5：实现真实浏览器观察闭环

**解决用户核心目标：AI 真正看见界面，并验证动作。**

涉及：Browser handlers、CDP Provider、已有结果出口、浏览器端到端测试。

实施步骤：

1. browser_snapshot 返回 MCP image，加 URL、标题、viewport、图像尺寸、observation_id 和有界元素信息。
2. browser_screenshot 复用捕获函数；默认直接传图，显式保存时才写文件。
3. 动作默认附带有界的后续观察；可关闭自动观察以控制输出量。
4. 分离动作执行结果与观察结果，观察失败不能把已经执行的动作标为可直接重试。
5. 跟踪 generation、页面导航与引用失效；必要时要求再观察，避免旧引用点击到新元素。
6. 校验截图缩放、DPR、页面滚动与坐标映射。观察不是原子事务，不承诺截图与异步 DOM 永远一致。
7. 用真实页面验证输入与点击；对需要可信输入事件或 Canvas 的场景采用 CDP Input，避免继续增加站点专用脚本分支。
8. 仅补验收实际需要的动作，例如滚动；不提前扩展其他桌面软件支持。

验收门槛：标准 MCP 客户端无需额外 view_image 就能完成“打开 → 看图 → 输入 → 点击 → 看结果”；断联时副作用动作不自动重放；全过程不创建 Workflow。

## 10. 阶段 6：资源、进程结果和 API 收尾

涉及：Session/进程管理、`processes.py`、`results.py`、Workflow engine/runs、server_info 与前端 DTO。

实施步骤：

1. Session 增加 generation、所有权、最后活动时间和租约；旧 generation 返回 SESSION_EXPIRED。
2. Supervisor 清理自有进程组和临时目录，启动 GC 保护活跃租约及其他 Profile。
3. 已连接的用户应用与 Workbench 创建的进程区分；未来桌面后端不得把 disconnect 实现为退出用户应用。
4. 统一进程 running/succeeded/failed/timed_out/cancelled/lost 状态，process_success 在运行或未知时为 null。
5. 终态失败时 ok=false；running 时 ok=true 只表示已受理，Workflow 不得据此宣称完成。输出 schema、摘要和工作流消费同时更新。
6. server_info 默认摘要，详细信息通过 sections/诊断查询，不隐式探测工具、不返回全机进程列表。
7. 现有 DB-015 临时 Workflow 只生成清理清单；删除需按明确授权清单处理。直接调用链路修好后不新增临时 Workflow 机制。

验收门槛：Profile A 停止不影响 B；重连没有旧 Session 误用；进程失败在 AI、UI 和 Workflow 中语义一致；默认 server_info 内容有界且无 Host 往返。

## 11. 15 个问题的落点

| 报告问题 | 处理阶段 | 处理决定 |
| --- | --- | --- |
| P0 Catalog 与 MCP 不一致 | 0、1 | 单一公共注册源，自动验证 invocation |
| P0 available 不代表在线 | 3 | 静态支持、配置与动态连接/可用性分离 |
| P0 Host 无 fail-fast | 3 | 心跳失效和 ack 独立截止时间 |
| P0 无恢复控制面 | 3、4 | 独立 Supervisor，status/reconnect/受控 restart |
| P0 browser_manage 权限并集 | 1、4 | 删除 facade，原子 Browser 工具独立 schema/权限 |
| P0 工具解析依赖 Host | 2 | 有效本地注册直接执行，Host 最后发现兜底 |
| P1 错误粒度不足 | 3、4 | request_id/generation/stage/cause 与有界时序 |
| P1 granted 后仍被 OS 拒绝 | 4 | 可行性预检、权限来源分离、准确失败分类 |
| P1 无受控诊断 | 4 | 只查询 Workbench 自有资源 |
| P1 Session generation/GC 缺失 | 3、6 | generation 失效、资源所有权、启动 GC |
| P1 聚合 schema 宽松 | 1 | 删除 Browser 聚合 schema，不增加联合兼容入口 |
| P1 exec_process.ok 误导 | 6 | 统一终态、退出码、成功字段与 Workflow 消费 |
| P2 server_info 巨大 | 6 | 默认摘要、详细信息定向获取 |
| P2 临时 Workflow 绕行 | 1、6 | 修直接调用根因，审查清单，不扩展临时工作流引擎 |
| P2 宽泛系统进程查询 | 4 | 合并到 host_diagnostics，不新增任意 bundle 查询 |

P0 六项完成的定义：阶段 1–4 的相关门槛全部通过，不能仅以修改 ToolDefinition 或增加 heartbeat 字段视为完成。

## 12. 发布、迁移与回退

1. 新契约在单一重构分支完成；各阶段有可审阅提交和独立验证，但不向用户同时发布两套入口。
2. 发布前备份相关配置和用户资产，运行引用预检。迁移脚本 dry-run 显示每个变更，识别不了的定义明确报告，不猜测或删除。
3. 数据迁移属于独立一次性步骤，迁移完成后运行态只接受新契约。已安装第三方客户端刷新 tools/list；用户自定义脚本按照破坏性变更说明更新。
4. 明确提升工具契约版本和 IPC 版本；发布版本按项目现有版本线确定，不机械套用现场汇总中的 0.2.x。
5. 回退使用旧发布包和对应资产备份，不在新代码中留旧实现开关或 fallback。
6. 涉及写操作的回退不能自动重放历史命令或浏览器操作。

## 13. 最终端到端发布门槛

- [x] Catalog、tools/list、直接 invocation 在同一客户端上下文完全一致。（自动化 Registry/Catalog 不变量与公共契约扫描通过）
- [ ] 正常 Browser 打开并完成图像观察和实际交互。
- [x] Worker crash、hang、陈旧/新鲜心跳竞态均小于 1 秒拒绝 Host 调用。（真实 crash 注入 + 陈旧 heartbeat + 新鲜 heartbeat/no-ACK 确定性测试）
- [x] Host 故障时注册 Node/Git/Python 的按名调用仍正常。（Runtime 本地注册/允许 PATH 不依赖 Host 的回归通过）
- [ ] 不重启 Runtime，Worker 恢复后可创建新 Browser session。
- [x] 旧 Session 明确失效，动作执行未知时不自动重发。（generation/SESSION_EXPIRED 与 action_state 契约已回归；不会自动重放动作）
- [ ] 同一 Desktop 多客户端、多 Profile 的授权、排队、停止与资源清理互不越界。
- [ ] 无效 OS 权限不会被应用内 granted 掩盖。
- [x] 进程运行/完成/失败在 MCP、UI、Workflow 中一致。（统一 process status/process_success 与 Workflow waiting_process 回归通过）
- [x] 无桌面 Server 部署继续正常启动，Host 能力准确显示不可用。（Runtime Host 控制面为可选依赖，Host 未配置/离线不阻断 Runtime）
- [ ] 包装后的 Desktop 实际验证启动、Host 重启、授权和关闭，不只在开发解释器中测试。
- [ ] DB-015B 在实际部署版本通过，无新建临时 workspace Workflow、无用户重启整个项目的绕行。

测试报告应记录构建版本、契约版本、平台、Host generation、request_id、故障注入方式和响应时间。本轮文档不代替这些实施验收。

当前源码自动化基线：Python `424` tests PASS（`5` skipped），前端 production build PASS，公共 Registry `32` 个工具契约检查 PASS。当前会话中的真实 Browser 尝试运行在上层 MCP 沙箱内部，Host Worker 无法读取宿主 LaunchServices/已注册 Chromium，按设计返回带 request_id/generation/ack/provider_start 的 `APP_RESOLUTION_FAILED`；该结果验证了失败分类，但不计作正常 Browser 门槛通过。包装构建前置条件检查同时发现当前源码环境缺少 bundled cloudflared 与 PyInstaller，因此包装 Desktop、真实宿主 Browser 和 DB-015B 三项必须在发布/部署环境继续验收，不能由解释器测试替代。
