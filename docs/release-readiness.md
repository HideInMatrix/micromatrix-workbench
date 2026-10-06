# 发布就绪审阅 — 更新于 2026-10-03

## 结论与范围

### 2026-10-02 桌面测试问题收口

补漏：`v0.5.9` 对已保存值的回填有效，但遗漏首次粘贴的输入事件顺序。`InputGroupInput` 转发的原生 `input` 先于其 `update:modelValue`，父组件读到旧空值，把本应 `set` 的新密码标成 `unchanged`，服务未保存后又按 metadata 清空表单。现 OAuth / 网络密钥统一消费 `update:modelValue` 的新值，原子更新输入与操作标记。新增实际编译 Vue 组件回归，复现旧代码失败，再验证首次粘贴 → 点击保存 → 真实配置路由/持久化 → 连续三次保存；勾选/不勾选保存均保持输入值，且不启动 Runtime。该补漏随 `v0.5.10` 发布，不改写 `v0.5.9`。

- 审批不再把用户拒绝、超时、客户端取消和 Runtime 停止合并为 `denied`；增加脱敏审计元数据、预取消检查、监听器清理及过期决定拒绝。UI 轮询有超时、失败提示与焦点恢复刷新；新请求通过 Tauri 原生桥提醒并激活窗口。修正 Button 包装器因忽略继承 props 而渲染 `div` 的问题，恢复按钮语义与原生禁用行为。
- 密钥保存、启停及路由切换后保留在前端内存中，默认掩码；选择保存敏感信息的 Tauri 用户，重启后通过固定本地配置路径的原生桥回填。没有向 HTTP/MCP 增加密钥读取接口，`unchanged` 的值也不夹带在普通 options 中发送。不保存则退出后不恢复；浏览器版不回读服务器明文。
- 正常 SemVer tag 在完整矩阵、校验与上传成功后自动发布正式 Release / Latest；`-rc` / `-beta` 仍是 Pre-release。保留草稿保护和禁止覆盖公开版本。不自动改写已发布版本；应用内更新的当前行为见末尾自动更新验收。
- 使用独立端口、临时 Workspace、合成密钥和离线 Cloudflare 替身进行了实际 Tauri 验收：保存/启动/停止/冷启动后的密钥框仍有值；真实 MCP `bash` 请求出现原生桌面审批弹窗，批准本次后返回预期输出。此项验证不等于真实公网 Tunnel 或所有网页客户端兼容；用户原始权限失败的调用缺少原始错误，不能声称已确定唯一根因。未改动用户运行中的服务和配置。
- 验证：76 个 Vitest、46 个 Node、2 个 Rust 回归通过；类型/Web 构建、Rust offline check、Actionlint 与重建 SEA 冒烟通过。隔离 HTTP 验证 native 密钥回填命令不可通过控制 API 调用。测试端口已释放，用户原实例仍运行。修复随新 tag 发布；不更改既有 Release 或安装位置。

源码默认开发版本为 `0.5.0`；发布构建已改为自动采用 Git tag 的完整 SemVer，不要求源码预先手动升版。本机最新 DMG 使用 `0.5.0`，本轮隔离 SEA 验证使用 `0.5.1`。初始审阅基于 `codex/pi-agent-mcp` 的未提交工作树；本地 master 先同步远端至 `eda8130`，再备份到 `codex/backup-master-synced-20260930`，最后用新版完整快照替换文件内容并保留双方提交历史。首次同步前的备份 `codex/backup-master-20260930` 仍保留。

**核心功能已有实现，生产部署验收仍有缺口。** 按当前分发要求，正常 SemVer tag 在完整矩阵和上传成功后自动发布正式 Release / Latest，无须手动公开；显式预发布 tag 保持 Pre-release。发布标签改变不等于安全缺口自动消失，剩余风险和真实 Tunnel / 跨平台安装验收继续保留。桌面自动安装更新已接入，当前行为与验证范围见末尾自动更新验收。

初始审阅没有修改业务实现；下方保留其复现证据，已修复项明确标注。后续修复重建了 SEA 并验证了真实浏览器交互。GitHub 的 `v0.5.2` 四平台构建、SEA 冒烟及草稿附件上传已成功；没有连接真实公网 Tunnel，干净机器安装验收仍待执行。

## 本轮修复跟进

- `v0.5.7` 的公开 Actions 元数据（运行 `36859491291`）显示仅 macOS arm64 在 `Build Tauri installers` 失败，Windows/Linux/macOS x64 成功、release 因完整矩阵未通过而跳过。用户日志确认 Rust 编译与 `.app` 签名成功，错误发生在 `bundle_dmg.sh`；完整日志 API 返回 403，尚不能确定内部失败的是 create/attach/Finder/sign 等哪个命令，不把类似上游问题当成本次根因。macOS CI 改为 Tauri 仅构建 `.app`，sidecar 冒烟后单独调用无 Finder DMG 脚本：ditto 保留应用，添加 Applications 链接，直接生成 UDZO 并校验；仅对明确临时忙碌错误最多三次重试，详细日志 always 上传，不重编译 Rust/Vite、不修改源 `.app`、不吞掉失败。本地 ARM64 实际 DMG 生成与只读挂载验收 PASS，原图标/三项二进制哈希与执行权限、深层签名、包内 cloudflared、sidecar 冒烟和产物收集均 PASS。类型/Web 构建、74 个 Vitest + 40 个 Node 测试、Actionlint PASS；修复后的 GitHub runner / x64 路径仍待重新发布验收。修复晚于 `v0.5.7`，重跑该旧 tag 不会自动使用新流程。
- Cloudflare Provider 补充 `auto / http2 / quic` 传输选择，分别展示自动、HTTP/2（TCP）、QUIC（UDP）；Quick / Named Tunnel 均传递所选 `--protocol`，旧配置默认 auto，环境变量支持覆盖。选项来自 Provider 表单元数据，API 与 Provider 都拒绝不支持的值；协议作为非敏感配置保存，不改变本地 MCP 的 HTTP 协议与手动启动规则。类型/Web 构建和本地 74 个 Vitest + 34 个 Node 测试 PASS，启动参数检查使用 mock，不连接 Cloudflare。隔离浏览器验证 HTTP/2、QUIC 切换/保存，刷新后选择保留且 Runtime 仍停止；macOS arm64 `.app` / DMG 重建及最终 sidecar 冒烟 PASS，三档配置均持久化且未启动 Tunnel。此次修改晚于已推送的 `v0.5.6`，不在该 tag 中；实际网络下两种传输可达性仍待验收。
- 恢复旧 Python 版根路径服务卡片：MCP 数据面的 `GET /` / `HEAD /` 返回公开服务信息，名称/版本与 MCP initialize 一致；协议列表来自锁定 SDK，工具名称/数量来自当前 Registry，认证链接使用相对路径，不读取 forwarded headers。不公开工作目录、配置和密钥，不改变 `/mcp` 的认证/审批，也不启动 Runtime。类型检查与 Web 构建 PASS；本地 49 个 Vitest + 33 个 Node 测试 PASS，覆盖三种认证模式、HEAD/405/404、MCP 客户端初始化与工具列表一致性。Git 仍不追踪 tests；SEA 冒烟脚本补充临时 External 配置的显式启动、根路径响应、未认证 MCP 返回 401、停止释放端口，供打包 CI 执行；不等同于实际公网 Cloudflare 验收。
- 上述服务卡片修复已重建 macOS arm64 SEA、最终重签名 `.app` 和 DMG（本地开发版本 `0.5.0`），原始 SEA 与最终 `.app` sidecar 的新增显式启动/停止冒烟均 PASS，包内 cloudflared 的离线 version/help 验证 PASS；未连接实际公网 Tunnel，未完成生产签名/公证。
- OAuth 超限输入（Content-Length 和 chunked）返回 413，HTTP 顶层捕获未知异常；服务随后仍能进行正常 MCP 调用。
- 配置/插件更新先验证和保存候选资源，再替换；Provider 校验或磁盘保存失败保留原 snapshot、工具、审批策略和磁盘配置。
- 内嵌 Web UI 使用同源控制地址，允许实际控制端口的 loopback Origin；恶意 Origin 仍拒绝。真实浏览器已验证自定义端口下页面加载、手动启动/停止、地址显示/清空。
- 应用只加载配置并启动控制 API。移除自动启动开关、API 和配置字段；旧 `enabled=true` / `MICROMATRIX_ENABLED=true` 被忽略。未完成 FRP 或 Workspace 配置不会在打开软件时执行，只有点击启动才检查。
- 生命周期操作已串行化；补充 start/configure、start/stop/start 回归和端口冲突检查。stop/start 会重建 OAuth 对象，使旧 token 失效。
- 此前 `0.5.0` 本地回归：Node 22.23.3 下原版 `npm run check` PASS（41 个 Vitest 测试 + 6 个 Web 测试 + 7 个脚本测试）；预构建 SEA 冒烟和 macOS arm64 DMG 构建 PASS。日志确认 verify 的 Vite 构建次数为 1，SEA 和 Tauri 为 0，Web 文件内容哈希保持不变；Rust 耗时报告已生成。此前 `cargo check --locked --offline` PASS。不能用 macOS 结果代替 Windows 原生验收。
- 工作流静态检查：Actionlint 1.7.12 PASS。macOS arm64 的 `CI=true APPLE_SIGNING_IDENTITY=- npm run tauri -- build --ci --bundles dmg -- --locked` PASS；产物收集与 SHA-256 校验 PASS。Unix 服务归档保留执行权限，打包测试确认不含 `.env.local`；macOS 无交互打包需设置 `CI=true` 跳过 Finder 布局脚本。
- 两次旧校验失败：运行 `36725895175` 的 `v0.5.0` 对上源码 `0.1.0`；运行 `36732602064` 的 `v0.5.1` / 提交 `235bcb0` 对上源码 `0.5.0`。已读取公开运行元数据，完整 job 日志需要登录，未直接下载。旧的版本相等校验现已删除，每个构建 job 根据 tag 自动同步 npm/Cargo/Tauri 配置、锁文件和显示版本；仅拒绝不合法的 SemVer tag。
- checkout/setup-node/upload/download 已升级为官方 Node 24 运行时的固定 SHA 版本；项目构建与 SEA 继续使用 Node 22.23.3。缓存优化已提交至 `235bcb0`，tag 自动版本及 tests 取消跟踪已提交至 `c1e41db`；重跑旧 tag 不会读取 master 的后续修复。
- 用户截图显示此前 macOS arm64/x64 和 Linux job 成功，Windows 在 `config.test.ts` 的 `/tmp` 路径断言失败，并非 Rust 编译错误。保留的本地测试已改用隔离的系统临时目录与平台路径解析；本轮按要求将所有 `tests/` 取消 Git 跟踪（17 个文件仍在本地），CI 不再执行这些测试。新克隆没有这部分回归保障，各平台仍执行类型检查和 SEA 冒烟。
- 前轮本地验证：`npm test` PASS（41 个 Vitest + 14 个 Node 测试）；新版 `npm run check` PASS（类型检查、Web 构建），Actionlint PASS。用不含 tests、私密配置或旧构建产物的临时源码副本模拟 `v0.5.1`，`npm ci --offline`、类型检查、Vite、预构建 SEA 和冒烟全部 PASS；实际 bootstrap 显示 `0.5.1`，Cargo `--locked --offline` metadata 和 Tauri 配置也为 `0.5.1`。另用临时配置验证 `v1.2.3-rc.1` 的版本同步，未重建该版本安装包。
- 2026-10-01 读取 GitHub 公开元数据：[运行 `36799631011`](https://github.com/HideInMatrix/micromatrix-workbench/actions/runs/36799631011)（`v0.5.2` / `c1e41db`）的 verify、macOS arm64/x64、Windows x64、Linux x64 和 `release-draft` 全部成功。旧流程只保存草稿，因此公开 Release 列表没有该版本。现改为校验附件 → 创建/复用草稿 → 全部上传成功 → 公开 Pre-release；不覆盖已公开附件，手动分支构建不发布。本轮 Actionlint 和 14 个本地构建/发布脚本测试 PASS，包含新建/复用草稿、上传失败、校验失败、禁止覆盖公开版本的离线模拟；自动公开修改尚未提交或远端验证，未通过本机操作发布现有草稿。
- 打包流水线改为 verify 上传一次 `shared-web`、各原生 job 下载复用；本地默认构建行为不变。按平台/架构隔离的 Rust 依赖缓存只在 master 写入，tag 读取默认分支缓存；需先手动对 master 预热，不承诺首次冷构建或 runner 排队加速。`rust-timings-*` 报告用于定位耗时；远端缓存命中效果待验证。
- 2026-10-01 按桌面分发要求，不再公开独立服务：发布 job 只允许 6 个安装包和一个合并 `SHA256SUMS.txt`；缺少/重复安装包、校验失败或已有草稿包含排除附件时拒绝发布。独立服务、JSON 和单独通知文件留在 Actions Artifacts，公开仓库的 Artifact 不视为私密存储。Node/Pi 许可证、通知与已知限制通过 Tauri resources 嵌入桌面包。本轮 20 个本地脚本测试、Actionlint、类型/Web 构建、SEA 冒烟及 macOS arm64 `.app` 构建通过，逐文件确认包内 4 个通知与源文件一致；Windows/Linux 的新资源打包待远端运行。修改尚未提交或推送，未更改现有线上附件。
- 2026-10-01 桌面启动故障复现：安装在 `/Applications` 的 `0.5.3` sidecar 从隔离配置启动后立即 SIGTRAP；crash report 首帧为 `pthread_jit_write_protect_np`。其签名有 `runtime` 但无 JIT entitlements，之前只验收打包前 SEA，遗漏了 Tauri 重签名后的实际运行。现保持 Hardened Runtime 并补充 V8 JIT/可执行内存权限，CI 增加最终 `.app` 中的 sidecar 冒烟。前端增加有界就绪等待、具体退出诊断和配置加载重试，不新增自动运行 Runtime/Tunnel。桌面冷启动又发现 Pi 在 SEA 中向上查找 `package.json`，触发 Documents 的 TCC 授权并阻塞同步读取；现仅在 SEA、且用户未显式配置 `PI_PACKAGE_DIR` 时固定到可执行目录，不扫描祖先 Workspace。名称统一 `micromatrix agent`，桌面 PNG/ICO/ICNS 与旧版备份逐字节一致，侧栏 SVG 不变；实际 `.app` 内 ICNS 也已核验。最终 macOS arm64 `.app` + DMG 构建及包内 sidecar 冒烟通过，Tauri 窗口冷启动直接显示配置与“已停止”，没有 `Load failed`；未点击启动、MCP 端口未监听。截图为 `/tmp/micromatrix-agent-idle-verified.png`。此前 macOS job 显式保留 `app,dmg`，避免只打 DMG 时 Tauri 删除 `.app` 导致冒烟误报；本轮改为仅由 Tauri 构建 `.app`，再独立制作 DMG，仍保留 `.app` 供冒烟且公开附件只选 DMG。类型/Web 构建、Actionlint、41 个 Vitest + 31 个 Node 测试通过；这里只验收闲置启动，不代表实际 Tunnel、审批或跨平台安装已通过。修改未提交/推送，未覆盖安装位置。

## 五项原始交付进度

### Cloudflare 分发遗漏修复（2026-10-01）

表单跟进：移除 Cloudflare 的 executable 输入项，其他 Provider 的路径字段和高级 API 覆盖保留。`FormField` 使用顶部对齐，避免同一行密钥附加状态文字把右侧 select 推低；InputGroup 的边框内控件统一为 32px 外部高度。类型/Web 构建及 9 项 Web、5 项控制命令回归通过，本机 `.app` 已重建；桌面视觉验收权限审核两次超时，DMG 在受限执行中未打包成功，未宣称截图或最新 DMG 已通过。未运行真实 Tunnel，未修改已安装版本。

此前桌面包只包含 Node SEA，Cloudflare 默认调用 PATH 上的 `cloudflared`，干净机器或 GUI 启动的 PATH 中没有它时会报 `Tunnel executable not found`。现 `build:sidecar` 按原生平台准备官方固定版本 `2026.9.3`，下载资产 SHA-256 锁定于 manifest，校验及 `--version` 失败阻止构建；Tauri `externalBin` 同时收录 cloudflared。SEA 默认使用相邻包内程序，保留明确的用户路径覆盖，源码开发仍使用 PATH；不修改全局 PATH、不安装系统服务、不启用自动启动，运行时禁用 cloudflared 自更新。Apache-2.0 许可证随桌面资源交付，独立服务归档仍只留 Actions Artifacts。

本轮本地 45 个 Vitest + 33 个 Node 测试、类型/Web 构建、Actionlint 和 macOS arm64 `.app` + DMG 重建通过；最终签名的包内 cloudflared 在无系统 PATH 环境下可执行 `--version` 与 `--no-autoupdate tunnel --help`，SEA 控制界面健康且 Runtime 闲置。其他桌面平台已配置原生下载/打包与预打包冒烟，实际安装待远端验收；没有连接真实公网 Tunnel，不能把 binary 冒烟当作 Tunnel 端到端验收。修改尚未提交或推送，未覆盖 `/Applications` 的安装版本。

| 交付项 | 已实现 | 未完成的验收 |
| --- | --- | --- |
| OAuth / CIMD | metadata、CIMD、授权码 PKCE、refresh、revoke、静态 Bearer；本机 OAuth → MCP → Pi 工具集成测试与 HTTP 异常回归通过 | 限流与状态容量、公网 issuer/proxy 信任策略、目标网页客户端实测 |
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

验收：所有请求的异常均有兜底；超限/断连/畸形输入得到确定的错误响应或受控断开；之后健康检查与正常 MCP 调用仍成功。CIMD 发现、登录、token 接口同时补充限流与内存状态上限/过期回收。

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

## 自动更新修复（2026-10-02）

本地默认版本已从 0.5.0 同步到可达发布 tag，桌面版本改读 Tauri 原生值。已接入 updater/process 插件、最小权限、正式版自动检查、自动下载安装重启；更新停止 Runtime 后再安装，不自动启动执行。更新签名强制绑定版本，发布清单按系统及安装格式选择包，发布前验证签名/版本/校验和；独立服务不作为 Release 下载。

已完成本地验证：76 个 Vitest 回归 + 56 个 Node 测试、5 个 Vue 真实组件测试、5 个 Rust 集成测试；类型检查 / Vite build / actionlint 通过。Rust release 与实际 macOS `.app` / `.app.tar.gz` 已在隔离目录生成，签名及签名版本校验通过，包内保留原图标、cloudflared、Node 服务和许可证。原生 updater 在临时应用目录完成签名下载与替换，篡改包和错版本均被拒绝；不等于 Windows / Linux 安装验收。

本机签名私钥已生成但不提交。GitHub `TAURI_SIGNING_PRIVATE_KEY` Secret 已配置，首个 updater 正式 Release `v0.5.11` 的四平台打包/发布及真实 macOS arm64 更新包隔离安装已通过；Windows / Linux / macOS Intel 实机升级仍待验收。缺少 Secret 时 workflow 会在 verify 提前失败。旧版无 updater，需手动安装首个支持更新的版本。原有 macOS 公证、Windows Authenticode、安全边界缺口不因此消失。

## 发布前的其他验收缺口

- Cloudflare Quick Tunnel 以 URL 日志作为 readiness；FRP 接受 login success；ngrok 正则能匹配一般 HTTPS 链接。均需用实际连接状态/可达性校验避免“有地址但未连通”。Tailscale 没有后台故障监测。
- SDK 当前声明最新支持协议为 `2025-11-25`，不能声称兼容所有最新 MCP 客户端。先声明并实测目标客户端/协议范围，不要求为了首版追新重写。[当前协议与旧版兼容说明](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- OAuth 的 stop/start 失效语义已修复并补测试；仍需完善 CIMD/密码认证限流、状态容量上限与过期回收。
- `tsc` + 通用 `*.vue` shim 没有完整检查 Vue SFC；补充与 TS 7 兼容的 SFC 检查路径及真实 UI 回归。
- `.github/workflows/ci.yml` 和 `desktop.yml`：push/PR 类型/构建检查，手动测试包，正常 tag 通过完整矩阵并上传成功后公开正式 Release / Latest；预发布 tag 保持 Pre-release。固定 Action SHA 与 Node/Rust 版本，自动采用 tag 版本并在 SEA 冒烟检查实际显示版本，收集校验和与 commit 元数据。tests 不随 Git 分发；本地回归结果不等于远端 CI 测试覆盖。远端四平台构建和草稿上传已通过，自动公开步骤、干净机器安装和生产签名仍未验收。
- `THIRD_PARTY_NOTICES.md` 目前只列 Pi；需要核对 Node SEA、前端、Rust 和其他被分发依赖的许可，并保证所需通知随最终包交付。这不是已完成的法律合规结论。
- 发布前仍须固定发布提交并重建产物；不要使用旧 tag 或旧工作树生成的构建元数据。tests 从后续提交移除，旧提交中的历史文件不会被改写。

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
5. 满足以上门槛后用指向已验收提交的新 SemVer tag 发布测试版。正式发布流程自动执行，但安全与兼容性验收不能以“构建成功”代替。

## 静默自动安装（2026-10-03，v0.5.12）

正式桌面版启动及每 6 小时检查后直接进入下载 → 强制签名/版本验证 → 停止 Runtime/Tunnel → 安装 → 重启，不弹应用确认框，也不要求点击更新。关于页显示进度，失败保留错误与手动重试；网络/签名失败不会停止运行中的 Runtime，停止失败不会安装，安装成功后保持执行锁直到重启。开发壳与浏览器不会自动安装。重启仍不启动 Runtime。

NSIS 显式当前用户安装，updater 使用 `quiet`；原生读取实际安装格式，MSI 保留无应用确认的 `passive` 模式，避免 quiet 无法提权导致退出后安装失败。静默不意味着绕过系统权限：MSI / Linux DEB 或不可写应用目录仍可能需要系统授权，MSI 可显示系统进度。未保存的表单不会自动保存，自动重启前须及时保存。`v0.5.11` 已安装用户升级到本次修复时仍使用其原有点击安装流程；进入本次修复后，后续正式版才自动安装。

本轮验证：76 个服务/插件 Vitest + 61 个 Node 回归 + 9 个真实 Vue 组件测试通过；类型/Vite build 与 Rust check 通过。Rust 安装格式策略 2 项通过；原生 updater 再次从真实 GitHub `v0.5.11` 下载、校验并替换临时 macOS arm64 `.app`，包内 sidecar、cloudflared 和图标保留。实际 App 启动与六小时定时路径已在组件测试中验证无点击下载安装重启，原生安装测试使用隔离应用，不覆盖用户安装。本轮修复随 `v0.5.12` 标签触发签名打包与正式发布；远端构建结果待本轮验收，不宣称已完成其他系统实机静默升级。所有 tests 继续忽略，不随 Git 分发。

## OAuth 旧版迁移说明

`v0.5.13` 曾以持久化动态注册修复重启后 `Unknown client or redirect URI`。当前未发布代码已按用户要求移除 DCR，包括旧注册文件读取/写入；该历史解决方案不再是当前架构。升级后随机 client ID 连接需改用 CIMD 重新授权，仅支持 DCR 的客户端不兼容。旧注册文件不自动删除，不影响新服务启动。

## Pi 扩展宿主、MCP 与 Skills 基础接入（2026-10-03，未发布）

Daemon 的执行工具已改为官方 Pi 工厂实际注册的工具，不再仅创建 BodyPlugin 工具后绕过扩展加载。执行宿主只驱动扩展与资源生命周期，不运行第二个模型循环。新增 MCP 桥接扩展、Skills 资源扩展及插件页添加入口；配置持久化、显式连接测试、启停和移除均通过本地控制面，不暴露为可供公网模型改写的管理工具。

真实临时 stdio 和 Streamable HTTP MCP 已完成握手、发现及经 Pi 注册后的调用；返回的 structuredContent 和原始 upstream isError 内容保留。读取声明不能绕过审批，未批准时外部工具执行标记文件没有产生。已验证同一 Runtime stop/start 重新加载、失败启动清理已连接子进程、配置保存不启动进程、Pi Skill 发现及按 ID 读取、名称冲突、schema 拒绝、hook 阻止和已审批参数不可被替换。UI 实际 Vue 组件回归覆盖添加/编辑 MCP、测试与保存分离、创建 Skill 及运行时锁定。

本地结果：91 个服务/插件 Vitest、61 个 Node 测试、12 个 Vue 组件测试通过；类型检查、Vite/服务构建通过。macOS arm64 实际 Node SEA 与 cloudflared 冒烟通过，并在 SEA 中验证 Skill 保存不启动、显式启动加载官方 Pi 宿主/资源并暴露工具、停止清空资源。测试目录继续忽略；未替换用户安装或修改运行中的 Runtime，未提交、推送或发布本阶段代码。

### 本阶段收口（2026-10-04，未发布）

- 本地密钥表单：空白保留、显式清除、保存不清空，变量不再依赖 GUI 继承终端环境。独立 `0600` 凭证文件和 rememberSecrets；不新增公网明文读取接口，不宣称磁盘加密。
- 外部 HTTP OAuth：标准 SDK discovery / CIMD / PKCE / refresh，系统浏览器显式授权、固定登记回环端口与 state/issuer 校验、取消/超时/注销；凭证绑定目标。缺少授权只提示登录，不自动打开浏览器。
- 远端工具目录：通知和手动刷新经 Pi 注册同步增删/定义变更，发现失败撤销工具；重置审批并拒绝已审批后被替换的定义。公网 GET 通知流受原有认证保护，停止会关闭活动流。
- Skill 文档编辑：Pi 验证、revision 冲突检查与原子替换。通过 Skill ID + 相对路径列出/读取支持文件，拒绝遍历、symlink 与超大/非 UTF-8 文件，不自动执行脚本。
- owned stdio 清理：Unix group TERM/KILL、Windows PID tree taskkill，多个 MCP 并行关闭。新增真实 descendant 忽略 TERM、挂起初始化/连接测试中途停止、运行中工具取消的清理回归。Tauri 退出先验证 owned sidecar PID，再请求 stop_runtime，6 秒上限后退出；并修正服务 SIGTERM 清理顺序。
- 控制面：补回环 Host/port 校验、JSON content type 与未授权 cross-site 拒绝（保留 WebView2/Tauri 受信 Origin），JSON Content-Length 和 no-store；仍未提供对本机恶意进程的身份隔离。

验收：98 个服务/插件 Vitest、61 个 Node、15 个真实 Vue 组件测试及 Rust owned-service 清理测试通过；类型/Vite、服务 bundle 和 macOS arm64 SEA 通过。SEA 实际验证无系统 PATH 下的内置 cloudflared、官方 Pi 宿主与 Skill 编辑/支持文件发现、外部 stdio 真实握手/本地密钥注入/注册以及测试/停止后的进程退出。测试目录继续不跟踪；未替换用户安装，未提交或发布。本机尚不能证明 Windows/Linux/macOS Intel 安装包实机行为；各平台 CI 已接入同一 SEA 冒烟，需新标签打包后验收。旧 SSE、DCR-only/服务特有 OAuth、恶意进程 breakaway 和 OS 沙箱不是本阶段支持项。

## CIMD-only 收口（2026-10-04，已纳入 v0.5.14 源码标签）

- 对外 OAuth 移除 `/register`、registration_endpoint、动态 ID、注册存储和旧注册文件依赖；public server card 标记 `clientRegistration: cimd`。CIMD/PKCE、issuer 响应、SSRF/有界缓存仍保留。
- 外部 OAuth 也移除注册 fallback，要求操作者托管自己稳定 HTTPS 文档、填写准确固定回环 callback。标准 SDK 仅做 discovery/CIMD 身份/PKCE/refresh；发现不支持 CIMD/S256/none 直接拒绝。旧配置可以加载并编辑，但不能继续动态注册登录；旧 OAuth token 不复用，已有本地密钥不清空。未配置或被占用的固定回调会明确报错。
- 旧动态客户端连接是破坏性迁移：网页客户端须使用 CIMD 重建连接；只有 DCR 能力的客户端/外部服务不支持。没有替用户部署客户端文档，不能声称公网外部 OAuth 即开即用。
- v0.5.14 的本机 fake-IP DNS 会使真实 ChatGPT 文档 GET 被安全校验拒绝；该问题现已在下述源码修复中验证。Windows/Linux/macOS Intel 安装包实机仍待验收。

本轮验收：177 个服务/插件测试、61 个 Node 测试、15 个真实 Vue 组件测试通过，类型/Vite/服务 bundle 与 macOS arm64 SEA 冒烟通过。已覆盖服务端无注册入口、重启按 URL 重新授权、损坏旧注册文件不读不改、外部 SDK 不 POST 注册、CIMD discovery 不兼容拒绝、固定 callback/state/PKCE/refresh、旧 token 迁移与身份/回调隔离，以及新增 CIMD 表单保存不启动。issuer 校验已实现；本阶段公开 ChatGPT 联调未通过 fake-IP DNS 边界，后续修复见下节。未跳过原认证/审批测试；测试目录保持不跟踪。

依据：[MCP 2025-11-25 授权规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)、[CIMD IETF 草案 -02](https://www.ietf.org/archive/id/draft-ietf-oauth-client-id-metadata-document-02.html)、[OpenAI CIMD/认证方法协商说明](https://developers.openai.com/plugins/build/auth)。CIMD-only 是本项目的主动兼容性取舍，不能把 DCR 描述为已被标准废除。

## CIMD fake-IP 修复（2026-10-05，v0.5.15 发布变更）

- 真实复现：系统 DNS 把 `chatgpt.com` 解析为 `198.18.0.13` / `::ffff:0:c612:d`，不是 ChatGPT 文档不支持 CIMD。原授权页将 DNS、网络和文档问题全部折叠成 invalid_client_metadata，错误提示失真。
- 仅对 fake-IP 回退固定 Cloudflare HTTPS DNS，所有恢复地址再次做公网校验，并保留原域名 Host/SNI、TLS 校验、不跟随重定向及 10 秒总期限；普通内网/保留地址不回退。回退只暴露元数据域名给该 DNS 服务，不传递文档路径、用户密码或 OAuth 状态。
- DNS/HTTPS 暂时不可用使用 HTTP 503 temporarily_unavailable；无效文档、unsafe URL、非公网地址和回调匹配失败继续拒绝，不能退回 DCR 或静态信任客户端文档。
- 在本机相同 fake-IP 环境使用真实 ChatGPT 公网文档验证：授权页 200、准确登记回调、密码授权 302、PKCE 换取 token 200、ChatGPT principal 及 refresh 200。仅使用临时本地测试服务器；未回跳到 ChatGPT，未更改用户已安装服务。真实桌面经公网 Tunnel 的 ChatGPT 接入仍需新包后验收。

本轮验收：205 个服务/插件测试、61 个 Node 测试、15 个 Vue 组件测试通过（合计 281），类型/Vite/服务 bundle 与 macOS arm64 SEA 冒烟通过。`npm run smoke:sidecar -- --public-cimd` 显式开启真实外网文档回归，并已在打包后 SEA 中通过授权页、PKCE、刷新检查；默认 CI 冒烟不强制依赖外站可用性。测试目录继续不跟踪。修复纳入 v0.5.15；v0.5.14 安装包不包含此修复。安装包与正式 Release 由标签工作流在全部构建成功后自动发布，源码标签不代表已完成安装包发布。

## Computer Use / ASIL 风格首版（2026-10-05，未发布）

- 独立 TS stdio MCP 模式，不构造控制面、Runtime/Tunnel 或第二个模型。macOS 固定 Swift Accessibility helper；跨平台 JSON 文件适配。共享 observe / validate / execute / post-state 协议，有效观察 ID、revision、一次性动作与独立目标验证。
- 插件页 Computer Use 只预填配置，默认只读，明确勾选才允许动作；通过现有 Pi MCP ExtensionFactory 注册，仍走同一审批入口。保存不启动，停止清理子进程；不请求系统权限，不绕过 OS 授权。Windows / Linux 原生桌面控制不在首版范围。
- macOS helper 已在构建阶段准备，平台 Tauri 配置加入 externalBin；本机最终 `.app` 实际包含 helper，签名检查与包内 SEA 冒烟通过。另已修正 Swift 默认继承构建机 macOS 27 的兼容性问题，Mach-O 最低版本核验为 11.0，平台配置同步为 11.0（未进行旧系统实机验收）。原图标、应用名、手动启动和更新签名设置保留；安装/发布行为未触发。
- 真实 SDK stdio 临时 JSON 语义修改与随机 marker 保留、回读验证、旧观察拒绝通过；真实 Pi HTTP 投影通过，一次批准才执行，拒绝时文件不变。包内 helper 权限检查和应用发现可用，未授权观察返回真实权限错误，不是模拟桌面执行成功。

本轮结果：231 个服务/插件测试、61 个 Node 测试、17 个 Vue 组件测试通过（合计 309）；类型/Vite/SEA 和最终 macOS arm64 `.app` 的包内冒烟、codesign deep/strict 校验通过。首次直接调用 Tauri 缺少 updater 私钥，补齐后本地默认未重签 Apple bundle 的 strict 校验仍失败；最终使用 CI 相同的 APPLE_SIGNING_IDENTITY=- 与项目既有 updater 密钥路径重建，签名校验及包内冒烟均通过，未生成或更换密钥。本机未授予 Accessibility，**真实 GUI 输入/按钮操作尚待用户授权后验收**；未证明 Windows/Linux/macOS Intel 的安装或原生控制。全部 tests 继续忽略，CI 用受跟踪的 SEA 冒烟覆盖基本链路。

未提交、推送、打 tag、替换用户安装或修改其 Runtime 配置。已有 v0.5.15 Release 不含此能力。使用与限制见 [Computer Use](computer-use.md)。

### 双平台系统代理与 Linux 暂停（2026-10-05，v0.5.16 发布变更）

- 取消直接绑定 MacDesktopAdapter，统一为 DesktopProxy + 惰性 NativeDesktopChannel。MCP/schema、审批、观察 TTL/revision、动作串行化、回读验证、关闭清理共用，OS descriptor 只选择原生 ABI 与允许的操作。
- macOS 保留 Accessibility/Swift；Windows 新增 .NET Framework 4.8 UI Automation/C# helper，支持 Value/RangeValue、Invoke、Toggle、SelectionItem、ExpandCollapse 及已观察应用的激活。显式 asInvoker/uiAccess=false manifest，不自动提权、不注入键鼠，不控制 UAC/锁屏/密码字段。原生错误保留 Win32/HRESULT 码。
- 两个平台分别编译并打包对应 helper，Windows .exe 路径/SEA 后缀正确分离；构建不下载 Python/PowerShell 解释器或在运行时编译模型代码。
- 暂停 Linux 客户端：移除桌面 matrix、安装包/更新条目、原生 build target 与 cloudflared 固定资产；Rust client/桌面工厂拒绝不支持系统。Linux runner 只保留 TS/Web 检查和 Release 附件整理。新 Release 为 4 个安装包、2 个 macOS 更新归档、latest.json 与 SHA256SUMS.txt，不删历史发布或用户文件。

本轮验证：236 个服务/插件、61 个 Node、17 个 Vue 回归通过（合计 314）。初次完整回归出现一次既有 Cloudflare 退出测试 5 秒超时，重跑全部通过；没有更改该超时或跳过测试。统一代理两个 OS 的契约测试是 backend doubles，不冒充实机 GUI。Windows 源码使用 Microsoft Roslyn 4.11、C#5 模式及 .NET Framework 4.8 引用实际交叉编译为 x64 PE，包含明确的无提权 manifest；临时编译工具仅在 /tmp，不加入产品或 Git。**未在 Windows 上运行 UIA，尚需 Windows CI 原生构建及实机交互验收**。macOS arm64 实际 SEA、最终 .app 内代理/helper 执行与 deep/strict 签名检查通过；辅助功能仍未授权，真实 GUI 动作未验收。测试目录继续忽略。本阶段源码随 v0.5.16 标签发布；安装包与正式 Release 必须等待标签工作流全部构建成功，不能用源码标签或本地验收代替安装包验收。

## Computer Use 内置管理与系统权限引导（2026-10-06，v0.5.17 发布变更）

- 新安装默认已经有内置 Computer Use，关闭但可用；无需手动添加 MCP、填写路径/参数。开关只保存状态，不能启动 Runtime/Tunnel。旧官方预填项归一化为内置配置，保留 enabled/readonly；不会覆盖同名第三方连接。当前安装生成 owned 程序/工作区参数，不执行旧安装路径。
- Runtime / 插件页都有设置卡，区分“已启用”“系统权限”“Pi 已连接”。macOS 启用后的无提示检查只查询固定 helper 信任；显式按钮才请求 TCC 并打开固定的 Accessibility 系统设置 URL。显示真实 helper 路径、手工添加方法、返回自动检查/重新检测与限时轮询；打开设置不代表授权成功，不代点系统开关。Windows 检查交互桌面，无自动提权、无 macOS 假流程。没有新增屏幕录制/完全磁盘权限。
- 本地检查不是公网工具执行，更不跳过外部 MCP open_world 审批。Start 仍显式、无 TCC 自动提示。首次接入的 ChatGPT 工具缓存需由用户在客户端刷新，程序不代改 ChatGPT 账户权限。Blender 专用建模适配仍不在本轮范围。
- 验证：243 个服务/插件 Vitest、61 个 Node、29 个 Vue 组件测试通过（合计 333），Rust 检查与 owned-service 清理测试通过。Type/Vite 构建、真实 macOS arm64 Node SEA、Pi 接入与审批、临时 JSON 回读、内置开关持久化/无隐式启动、原生权限检查全部通过。本机仍是 Accessibility=false，未修改系统授权；权限申请后的授予与真实 GUI 动作未作实机验收。Vue 权限授予/返回检测和 Windows UI 状态用契约替身覆盖，不冒充原生成功。
- 隔离的嵌入式 Web 预览实际显示预装关闭开关；未替换 /Applications 客户端、修改用户 Runtime/秘密或开启用户 Tunnel。所有 tests 继续忽略；新增关键检查也纳入跟踪的 SEA 冒烟脚本。本轮使用 v0.5.17 源码标签；安装包和自动更新仍以远端工作流成功后的正式 Release 为准，v0.5.16 不含本轮改动。

- 界面收口：Runtime 状态区压缩为页头徽标，统一页宽和间距；移除重复微文案，技术说明折叠展示，必要审批/权限/错误保留。补充 Runtime 设置与内置插件同时可见、帮助默认收起的 Vue 回归；在 900px 桌面最小窗口宽度验证实际嵌入式预览，未启用用户 Runtime 或修改安装。
