# 实施顺序与验收

状态：源码整改完成，自动化回归通过；实际包装 Desktop、真实宿主 Browser 与 DB-015B 部署验收仍需在发布环境执行。

2026-09-11：以下完成记录针对 Browser/Host 整改。0.4.x 新增的浏览器、Blender、Figma 通用桌面观察与操作尚未实施，见 [0.4.x 计划](../desktop-computer-use-04/README.md)；不得将以下完成项视为通用桌面能力已完成。

- [x] 1. 固定真实工具契约并消除目录误报
  - 建立 Catalog invocation ∈ tools/list 的不变量测试，覆盖目前 17 个失配入口、Browser、Git、Process、Skills、Workflow 和外部 MCP。
  - Browser 原子工具正式公开，删除 browser_manage；其他域私有方法退出公共注册。
  - 更新目录、服务摘要、工作流引用、前端消费；检查固定参数与目标 schema 一致。
  - 盘点旧引用，定义带备份的一次性迁移，禁止运行时 alias/fallback。
  - _Requirements: R1, R2, R8, R17_

- [x] 2. 拆开 Runtime 本地执行与 Host 发现
  - 删除已注册程序每次必须核对 Host 的执行路径；维护指纹和项目版本约束。
  - Host 缺失时正常运行已注册及允许范围内的工具；注册过期不静默换版本。
  - 此项可在 Host 生命周期改造前独立验证，避免扩大故障影响。
  - _Requirements: R6, R7_

- [x] 3. 建立最小可独立恢复的 Host 生命周期
  - 从 DesktopPermissionBroker 移出 Provider 执行到独立 Worker；用存活 Supervisor 管理控制面和自有资源。
  - 统一 HostConnection、稳定端点身份、generation、ack 和请求 deadline。
  - 删除旧混合执行循环，隔离路径解析、Browser 与 Host Identity 队列。
  - 提供可在 Worker 失效时使用的 host_status / host_reconnect，建立有界自动重启。
  - _Requirements: R3, R4, R5, R12_

- [x] 4. 明确授权、诊断和受控重启
  - 分开 Runtime 会话授权、Browser 观察/控制与 Host 管理权限，完成已知可行性预检。
  - Supervisor 返回结构化阶段错误、有界脱敏日志；管理重启按影响范围授权。
  - 授权 UI 使用独立 composable；无效授权和系统权限缺失可被解释。
  - _Requirements: R8, R9, R12, R13_

- [x] 5. 打通浏览器图像观察闭环
  - 利用现有 _image 输出，不引入新的结果传输层。
  - Browser snapshot 返回图像与结构化信息，动作后观察有独立结果状态。
  - 验证正确坐标、引用失效、输入事件和真实页面效果，补必要的滚动等动作。
  - _Requirements: R10, R11_

- [x] 6. 收尾资源与 API 语义
  - generation/租约失效、启动 GC、进程组清理，只管理 Workbench 自有资源。
  - 同时更新进程状态、结果摘要、工作流等待与失败判断。
  - server_info 默认摘要；静态契约 revision 与动态健康 revision 分开。
  - 不新增 ephemeral workflow；报告已有 DB-015 临时资源清单供明确清理。
  - _Requirements: R14, R15, R16_

## 故障矩阵

| 场景 | 预期 |
| --- | --- |
| Browser 正常打开、观察、输入、点击 | 标准客户端直接收到图像并完成真实页面流程，无临时 Workflow |
| Worker 已死亡，心跳过期 | 所有依赖 Host 的调用小于 1 秒失败；host_status 立即可读 |
| 心跳刚更新后 Worker 死亡/卡死 | 请求 ack 截止时间内失败，不等待 30 秒 |
| Browser Provider 卡住 | 状态与管理控制面仍可用，普通工具解析不被队列拖住 |
| Host 离线 | 已注册 Node/Git/Python 正常；未知工具快速说明缺少 Host；不偷偷换版本 |
| Worker 重启 | 原 Runtime 不重启；新 Browser session 可用，旧 session 明确过期 |
| 动作已确认后断联 | 返回已执行/未知状态，不自动重放点击、提交或输入 |
| 一个 Profile 停止，另一个仍运行 | 只取消和清理停止 Profile 的资源 |
| Browser 授权后请求 Host restart / Host Identity | 未获得其他权限，不能借用 Browser 授权 |
| 操作系统权限缺失 | 返回可行动的系统权限错误，无声称已修复的无效应用授权 |
| 进程 running / 非零退出 / timeout | UI、AI 与 Workflow 对状态和成功判定一致 |
| Catalog 查询期间心跳变化 | 静态 contract_revision 稳定；invocation 目标与公共工具始终一致 |
| 新版本读取旧 Workflow 引用 | 预检明确识别并通过一次性迁移更新；不自动运行兼容路径 |
| 无桌面的 Server 部署 | Runtime 正常启动，Host supported/configured/ready 准确，不导入必需 GUI 依赖 |

时间要求同时使用确定性时钟测试与真实故障注入验证；不能只 mock configured=true 或用自家宽松服务器互测后宣称通过。实际 DB-015 环境验收需记录部署构建版本、工具契约版本、Host generation 与关联 request_id。

## 本轮源码验收记录

- Python 全量回归：`424` tests，`5` tests 按平台条件 skipped，其余 PASS。
- 前端：`pnpm build` PASS，包含代码规范、TypeScript、Vue TypeScript 与 Vite production build。
- 公共工具契约：Registry 共 `32` 个公开工具；Browser 9 个原子工具及 Git/Process/Workbench facade 存在，旧 `browser_manage`、细粒度 Git/Process/Workbench 调用入口不在公共 Registry。
- Host 生命周期：真实独立 Worker crash 故障注入、generation 轮换、旧 Browser Session `SESSION_EXPIRED`、受控 restart 与自有 generation GC 已通过；Broker 连续创建/关闭压力验证 `25/25` PASS。
- fail-fast：无/陈旧 heartbeat 直接失败；新鲜 heartbeat 但无 Worker ACK 的确定性测试在 1 秒内返回 `HOST_ACK_TIMEOUT`。
- 进程契约：running / succeeded / failed / timed_out / cancelled 以及 `process_success`、Workflow `waiting_process` 已进入回归；`lost` 保留为进程所有权丢失时的统一终态。
- 旧 Workflow：启动预检采用 backup-first 一次性迁移；无法安全迁移会报告并拒绝继续，不提供运行时 alias/fallback。
- Browser 源码闭环：snapshot/image、post-observation、stale ref、输入事件与结构化 action state 均已实现并进入契约测试。当前会话尝试真实 Browser E2E 时，嵌套 MCP 沙箱无法访问宿主 LaunchServices/已注册 Chromium，正确返回 `APP_RESOLUTION_FAILED`，因此不把该尝试记为真实宿主 Browser PASS。

## 发布环境仍需执行

- 在未被上层 MCP 沙箱限制的包装 Desktop 中完成 Browser open → snapshot/image → fill/press/click → screenshot → close 实际页面闭环，并记录 generation/request_id。
- 用包装后的 Desktop 验证 Worker restart、授权 UI、关闭与资源回收；当前源码环境缺少 bundled cloudflared 且未安装 PyInstaller，不能据源码解释器测试替代此门槛。
- 在 DB-015B 实际部署版本执行最终 Browser gate；不得新建临时 workspace Workflow，也不得要求用户重启整个项目作为绕行。
