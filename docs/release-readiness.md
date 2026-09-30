# 发布就绪审阅 — 2026-09-30

## 结论与范围

当前应用版本标识 `0.5.0`，按已推送的 `v0.5.0` tag 同步；初始审阅使用 `0.1.0`，最新本机安装包构建使用 `0.5.0`。初始审阅基于 `codex/pi-agent-mcp` 的未提交工作树；本地 master 先同步远端至 `eda8130`，再备份到 `codex/backup-master-synced-20260930`，最后用新版完整快照替换文件内容并保留双方提交历史。首次同步前的备份 `codex/backup-master-20260930` 仍保留。

**核心功能闭环已经具备；适合继续内部开发验证，不具备公开发布的验收条件。** 本轮已修复前三项阻塞，剩余安全边界、桌面退出与真实 Tunnel 验收完成后再发布 `0.5.0-alpha.1`；当前不能宣称稳定版或跨平台正式支持。

初始审阅没有修改业务实现；下方保留其复现证据，已修复项明确标注。后续修复重建了 SEA 并验证了真实浏览器交互；GitHub 打包工作流也已补充。没有连接真实公网 Tunnel；macOS arm64 已用工作流固定的 Node 22.23.3 重建 DMG 与独立服务压缩包，跨平台远端运行与干净机器安装验收仍待执行。

## 本轮修复跟进

- OAuth 超限输入（Content-Length 和 chunked）返回 413，HTTP 顶层捕获未知异常；服务随后仍能进行正常 MCP 调用。
- 配置/插件更新先验证和保存候选资源，再替换；Provider 校验或磁盘保存失败保留原 snapshot、工具、审批策略和磁盘配置。
- 内嵌 Web UI 使用同源控制地址，允许实际控制端口的 loopback Origin；恶意 Origin 仍拒绝。真实浏览器已验证自定义端口下页面加载、手动启动/停止、地址显示/清空。
- 应用只加载配置并启动控制 API。移除自动启动开关、API 和配置字段；旧 `enabled=true` / `MICROMATRIX_ENABLED=true` 被忽略。未完成 FRP 或 Workspace 配置不会在打开软件时执行，只有点击启动才检查。
- 生命周期操作已串行化；补充 start/configure、start/stop/start 回归和端口冲突检查。stop/start 会重建 OAuth 对象，使旧 token 失效。
- 最新 `0.5.0` 回归：Node 22.23.3 下 `npm run check` PASS（13 个 Vitest 文件 / 41 个测试 + 6 个 Web 测试 + 7 个构建/发布脚本测试）；预构建模式的 SEA 冒烟和 macOS arm64 DMG 构建 PASS。日志确认 verify 的 Vite 构建次数为 1，SEA 和 Tauri 为 0，Web 文件内容哈希保持不变；Rust 耗时报告已生成。此前 `cargo check --locked --offline` PASS。Windows 原生结果仍待远端重新运行，不能用 macOS 结果代替。
- 工作流静态检查：Actionlint 1.7.12 PASS。macOS arm64 的 `CI=true APPLE_SIGNING_IDENTITY=- npm run tauri -- build --ci --bundles dmg -- --locked` PASS；产物收集与 SHA-256 校验 PASS。Unix 服务归档保留执行权限，打包测试确认不含 `.env.local`；macOS 无交互打包需设置 `CI=true` 跳过 Finder 布局脚本。
- GitHub 运行 `36725895175` 已在 tag `v0.5.0` / 提交 `87ea725` 的 verify 失败：应用配置仍为 `0.1.0`，本地带相同 tag 复现了版本校验拒绝。完整 job 日志需要登录，未直接下载。当前已将应用配置、锁文件和显示版本同步为 `0.5.0`，保留错误 tag 拒绝规则，并新增版本一致性回归。
- checkout/setup-node/upload/download 已升级为官方 Node 24 运行时的固定 SHA 版本；项目测试与 SEA 构建继续使用 Node 22.23.3。本轮修复尚未推送，远端打包矩阵与 Draft Pre-release 仍需通过新提交的真实运行验证；重跑旧 tag 不会读取 master 的修复。
- 后续用户截图显示 macOS arm64/x64 和 Linux job 成功，Windows 在 `config.test.ts` 的 `/tmp` 路径断言失败，并非 Rust 编译错误。本轮测试改用隔离的系统临时目录与平台路径解析，未禁用 Windows 测试。
- 打包流水线改为 verify 上传一次 `shared-web`、各原生 job 下载复用；本地默认构建行为不变。新增按平台/架构隔离的 Rust 依赖缓存，只在 master 写入，tag 读取默认分支缓存；需先手动对 master 预热，不承诺首次冷构建或 runner 排队加速。新增 `rust-timings-*` 报告产物；本轮优化未提交或推送，远端缓存命中效果待验证。

## 五项原始交付进度

| 交付项 | 已实现 | 未完成的验收 |
| --- | --- | --- |
| OAuth / DCR | metadata、DCR、授权码 PKCE、refresh、revoke、静态 Bearer；本机 OAuth → MCP → Pi 工具集成测试与 HTTP 异常回归通过 | 限流与状态容量、公网 issuer/proxy 信任策略、目标网页客户端实测 |
| Tool approval / 危险策略 | safe/trusted/dangerous；单次与认证会话授权；停止清空审批；Workspace canonical 路径边界；基础生命周期并发回归 | 控制面访问防护、真实桌面审批交互验收；Shell 不是 OS 沙箱 |
| Tunnel Providers | External、Cloudflare、ngrok、FRP、Tailscale 的实现；executable/config preflight；部分进程退出监测 | 各 Provider 真实连接与可达性验收；readiness 判定、Tailscale 状态监测与配置归属清理 |
| Web / Tauri UI | Vue 3 + Vite 8、Runtime 状态、插件开关、网络与密钥配置、审批、Sonner；Tauri 2 壳；内嵌网页同源与手动启停实测 | 完整 Vue SFC 类型检查、浏览器/桌面自动化、异常退出提示 |
| 单文件服务与静态资源 | CJS 内嵌 UI、Node SEA、macOS arm64 sidecar 冒烟和 DMG、独立服务归档与校验和；GitHub 打包工作流 | 活动 Tunnel 下的退出清理；生产签名/公证、干净机器验收、完整许可证清单与远端发布流水线验收 |

实现数量不能换算成可靠的完成百分比：五项都已有代码，但并非五项都达到发布标准。

## 架构判断

### 保留当前主结构，不推倒重写

```text
网页模型（推理 / tool selection）
  → MCP 数据面 → approval gate → BodyPlugin → Pi AgentTool.execute
                                  ↑
Vite / Tauri → loopback control plane → RuntimeSupervisor
                                  ↓
                            NetworkProvider
```

- 模型与执行分离符合“网页大脑、本地身体”的目标，没有重复维护本地模型循环。
- Workspace / Shell 工具复用 Pi；MCP、网络、UI 不自行实现业务工具。
- 控制面与数据面分开，审批集中在执行前，Provider 只负责发布地址，边界清楚。
- Pi 精确版本锁定与 CJS → SEA → Tauri 的包装路径可保留。

### 必须纠正的设计边界

- 当前是 **Pi 工具驱动的 MCP 执行服务**，不是完整本地 Pi Agent/session runtime。不要以“完整 Agent 内核”描述它。
- BodyPlugin 已形成源码级插件边界，但 Runtime 仍硬编码 Workspace / Shell。它不是任意第三方插件安装/热加载系统；首版不需要为此扩展范围。
- Runtime 已有串行生命周期操作与配置事务；仍需验收真实 Tunnel 和桌面强杀/超时退出路径，不能仅用 `running` 布尔值代表全部交付状态。
- 审批目前按工具名称分类，新增插件时应由插件声明能力/风险，再由 gate 判定，避免未来插件复用 `read` 等名称而被自动放行。当前只内置两个插件，不把这一改造作为首版必需功能。
- Workspace 路径边界不是进程沙箱。Shell 能使用服务账户拥有的权限，这项限制应继续明确告知用户。

## 初始审阅发现与修复状态

### 已修复 — OAuth 请求可以终止整个服务（初始已复现）

位置：`packages/mcp-server/src/http-service.ts:39,71-73`；`packages/oauth/src/local-oauth.ts:72-81,310-311`。

向隔离子进程的 `/token` 发送约 70 KB 的表单，无需认证。`readBody` 抛错，HTTP 顶层没有 catch，Node 子进程退出码 **1**，错误为 `OAuth request body is too large`。不是普通的 4xx 拒绝，而是整个服务退出。

验收：所有请求的异常均有兜底；超限/断连/畸形输入得到确定的错误响应或受控断开；之后健康检查与正常 MCP 调用仍成功。DCR、登录、token 接口同时补充限流与内存状态上限/过期回收。

### 已修复 — 配置更新失败会破坏原运行状态（初始已复现）

位置：`apps/daemon/src/runtime.ts:138-173,204-209`。

从合法 External 配置切换到缺少字段的 FRP 配置：调用报 `FRP requires a client config file`，但 snapshot 的 provider 已变成 `frp`，工具数量从 **6 变成 0**。代码先修改配置并 dispose 旧 registry，再创建新资源；失败后没有回滚。

验收：先验证并构建候选配置/资源，再以事务方式替换和持久化；任何失败都保留原配置、工具和可启动状态。保存到磁盘失败也需要一致性策略。

### 已修复 — 内嵌网页的同源 API 被拒绝（初始已复现）

位置：`packages/control-plane/src/http-service.ts:8-14,80-87`；`apps/web/src/api/desktop.ts:17`。

`POST /api/desktop` 携带控制服务自己的 Origin 得到 **403 `origin_not_allowed`**。白名单只有 Vite 和 Tauri，没有控制服务自己的 origin。自定义控制端口还会遇到前端固定回退到 8233 的问题。

现有 sidecar 冒烟只用 Node fetch，不发送浏览器 Origin，且 Runtime 禁用，所以其 PASS 不能证明内嵌 UI 交互或工具执行可用。

验收：真实浏览器加载打包服务上的页面，bootstrap、配置保存、启动停止、审批均成功；同时验证默认和非默认控制端口。

### 已修复并补回归 — 生命周期切换缺少并发隔离（初始代码确认）

位置：`apps/daemon/src/runtime.ts:74-75,118-119,138-140,186-194`。

启动期间 `running=false`，configure / plugin toggle 可以替换正在启动的资源；start 遇到任意 transition 都返回该 promise，包括停止操作。配置入口也没有复用加载配置时“控制端口不能等于 MCP 端口”的约束。

验收：定义操作串行化/拒绝规则，覆盖 start/start、start/stop、start/configure、stop/start、插件切换和端口冲突；保证无旧监听器/子进程泄漏。

### P1 — 桌面退出不是服务的优雅关闭（代码确认，未实测活动 Tunnel 残留）

位置：`src-tauri/src/lib.rs:35-38`；`apps/daemon/src/main.ts`；`packages/network/src/tailscale.ts`。

Tauri 退出调用 shell plugin 的 `CommandChild.kill()`。本机锁定的 plugin 实现委托给 `shared_child`，Unix 使用 **SIGKILL**；服务的 SIGTERM 清理不会执行。正在运行的 Tunnel 子进程和后台 Tailscale Funnel 存在残留风险。当前 SIGTERM 冒烟没有覆盖这个退出路径。

验收：先请求服务停止 MCP、拒绝待审工具、终止 owned Tunnel，再有界退出；超时才强杀。活动 Tunnel / 待审批 / 执行中的工具 / 服务已崩溃各场景都要验证进程和端口释放。Tailscale 不应无条件 reset 用户的全部 Funnel 配置。

### P1 — 控制面与公网信任边界未完成（部分已复现）

位置：`packages/control-plane/src/http-service.ts:79-106`；`packages/mcp-server/src/http-service.ts:101-105`；`packages/oauth/src/local-oauth.ts:45-50`。

- 控制面绑定回环且检查存在的 Origin，这是基础防护；但缺少 Host 校验/本地会话凭证。隔离验证中，无 Origin、异常 Host、`text/plain` 的 API 请求仍返回 **200**。这证明请求被接受，不等同于已经复现完整 DNS rebinding 攻击。
- MCP transport 没有显式配置 Origin/Host 防护；已核验锁定 SDK 的 `webStandardStreamableHttp.js`，`enableDnsRebindingProtection` 默认是 `false`。认证不能替代来源验证。
- OAuth issuer / resource 根据请求中的 forwarded headers 推导，没有明确可信代理或固定 public origin 策略；需要约束可信入口。

验收：预期 UI origin 允许，恶意 Host/Origin 与不合法更新请求拒绝；代理头仅在可信网络路径使用；同时回归真实 Tunnel 下的 OAuth callback/resource 校验。

MCP 官方明确要求 Streamable HTTP 服务校验 Origin，并建议本地回环绑定和认证；控制 API 不是 MCP 协议端点，但它同样管理本机执行能力，不能只依赖监听地址。[官方 Transport 安全要求](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#security--endpoint)

## 发布前的其他验收缺口

- Cloudflare Quick Tunnel 以 URL 日志作为 readiness；FRP 接受 login success；ngrok 正则能匹配一般 HTTPS 链接。均需用实际连接状态/可达性校验避免“有地址但未连通”。Tailscale 没有后台故障监测。
- SDK 当前声明最新支持协议为 `2025-11-25`，不能声称兼容所有最新 MCP 客户端。先声明并实测目标客户端/协议范围，不要求为了首版追新重写。[当前协议与旧版兼容说明](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- OAuth 的 stop/start 失效语义已修复并补测试；仍需完善 DCR/密码认证限流、状态容量上限与过期回收。
- `tsc` + 通用 `*.vue` shim 没有完整检查 Vue SFC；补充与 TS 7 兼容的 SFC 检查路径及真实 UI 回归。
- 已补充 `.github/workflows/ci.yml` 和 `desktop.yml`：push/PR 检查，手动测试包，tag 通过完整矩阵后生成 Draft Pre-release。固定 Action SHA 与 Node/Rust 版本，验证应用/tag 版本，收集校验和与 commit 元数据。跨平台远端运行、干净机器安装和生产签名仍未验收，不能因新增 YAML 宣称发布流水线已经在 GitHub 跑通。
- `THIRD_PARTY_NOTICES.md` 目前只列 Pi；需要核对 Node SEA、前端、Rust 和其他被分发依赖的许可，并保证所需通知随最终包交付。这不是已完成的法律合规结论。
- 新版实现、集成测试和构建脚本随本地 master 迁移一并提交；发布前仍须固定发布提交并重建产物，不能直接使用迁移前工作树生成的构建元数据。

## 初始审阅验证结果（修复前证据）

| 检查 | 结果与范围 |
| --- | --- |
| `npm run check` | PASS：typecheck；10 个 Vitest 文件 / 34 个测试；3 个 Web 模型测试；Vite build |
| `npm run check:sidecar` | PASS：重建 macOS arm64 SEA；静态页面/API；Runtime 禁用时 SIGTERM 后控制端口释放 |
| `cargo check --manifest-path src-tauri/Cargo.toml --locked --offline` | PASS：Rust 编译检查，不等于安装包验收 |
| 隔离配置失败复现 | FAIL：拒绝 FRP 更新后配置已改变、工具 6 → 0 |
| 隔离控制面同源/Host 检查 | FAIL：合法同源 Origin → 403；异常 Host 无 Origin → 200 |
| 隔离 OAuth 超限请求 | FAIL：服务子进程退出码 1 |

测试初次运行被环境的 loopback 监听限制阻止；允许本地端口后重新运行成功，不把 EPERM 计作项目故障。所有专项复现使用临时配置与临时端口，未改动正在运行的实例。

## 下一步顺序

1. HTTP 异常边界、配置事务、内嵌网页访问和手动启动已修复；保持失败路径回归。
2. 继续修复控制面/代理信任策略、OAuth 限流与 Tauri 优雅退出，并扩展异常生命周期回归。
3. 选定首版支持的 Tunnel / 网页客户端 / 平台做真实验收；未验收 Provider 明确标记实验性。
4. 固定发布提交，补充许可证分发，重建并在干净机器测试安装包，输出校验和与限制说明。
5. 满足以上门槛后发布 `0.5.0-alpha.1`。正式版再以稳定性和已声明的平台/客户端矩阵验收，不以“构建成功”作为发布条件。
