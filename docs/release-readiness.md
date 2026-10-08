# 发布就绪 — 2026-10-08

## 结论

本页记录 v0.5.21 发布前的验收证据与已知限制。用户已要求提交、推送并触发正式发布；tag 流水线仍须通过完整原生矩阵、签名和附件门槛才会公开 Release，并被现有客户端静默更新。公网、Windows 实机等未验收项目保留为已知限制，不能把本地代码测试通过描述成所有平台生产验收完成。

旧的逐版本故障记录已从本页移除，避免将修复后的能力仍列为待实现。当前证据与限制如下。

## 已收口

| 范围 | 实际证据 | 边界 |
| --- | --- | --- |
| macOS 正式身份 / 权限复用 | 已安装 0.5.19 与新签名 0.5.20 候选包均返回 `org.micromatrix.computer-use`、`signing_mode=certificate`、`Accessibility=true`。候选包位于工作区，启动多个新会话均复用已有授权，无授权请求 | Dev 使用独立 `.dev` 身份，返回 false 不代表正式版未授权；未覆盖用户安装、不写 TCC、不安装可信根。自签名不是 Apple 公证 |
| 原生 GUI → MCP → JavaScript 批量执行 | 本轮早期签名候选包对自建真实 AppKit 窗口，通过 QuickJS/AX `set_value` 填入随机 marker；操作返回 executed、独立 GUI 进程持久化及再次观察均一致。最终候选包重新验收时确认会话已锁屏，原生动作记为 UNVERIFIED | 不是 mock，也不是 Blender 建模验收。不操作个人应用、不解锁。最终包实际 Screen Recording 拒绝及无图像返回通过；正向截图/坐标输入未验收，不自动申请 |
| Home MCP 的 Internal error | 已连接工具返回 `-32603 Internal error`；只读公网请求返回 HTTP 530 / Cloudflare 1033，本机没有 micromatrix 服务进程。独立已安装 stdio 服务和 helper 正常 | 当前公共入口不在线；不能据此诊断为 AX 权限或本地工具实现错误。不自动替用户启动 Runtime |
| 实际 ChatGPT CIMD | 不替换 resolver，真实 DNS/TLS 解析 `https://chatgpt.com/oauth/client.json`；隔离 loopback 服务完成授权页、PKCE/code/token、SDK MCP read、refresh 轮换/旧值拒绝及 Stop | 使用随机临时密码/workspace，不登录用户账号、不访问 ChatGPT callback；不冒充网页端账号或公网 Tunnel 验收 |
| HTTP / OAuth 安全与生命周期 | 固定 issuer/resource，Host/Origin 校验，S256 格式，限流、有界状态与过期回收，容量拒绝保留 grant；悬挂 HTTP body、真实进程 readiness 取消及 owned descendant 清理专项通过 | 全局登录额度可能影响同时授权用户；Workspace/Shell 并非 OS 沙箱。审批与系统权限不可被模型绕过 |
| Tunnel 启动/停止 | URL 须等待连接注册及实例 nonce；串行监测失败撤销地址。所有受管 Provider 接入启动取消；Tailscale 启动中的 CLI 先取消/等待结束，再检查并关闭 owned route，并发 Stop 合并 | Tailscale 路由有外部变更时保留用户配置，不 global reset；CLI 归属快照不是原子 CAS。Tailscale 取消/账号逻辑使用明确标注的契约 fixture，不是实际账号测试 |
| macOS/Windows 通知文件 | 目标解析图分别为 arm64 436、Intel 437、Windows 430 项；严格通知检查均无缺失。补充 21 个 Cargo 档案的版本/commit/哈希绑定通知；npm 缺口为 0；固定 Rust std 通知用于最小 CI profile | objc2 保留 Apple SDK 上游提示；sigchld/部分 objc2 无独立许可正文时，保存原始声明和明确标记的标准 MIT 补充文本，不编造版权人。`legalReviewComplete=false`，不是完整法律审计结论 |
| 原生发布回归 | 每个 macOS/Windows job 都运行实际 SEA + Chromium/Playwright + QuickJS 回归、通知严格门槛、owned process 测试；可用授权桌面才执行自建原生 GUI fixture | Headless runner 无交互桌面时打印 UNVERIFIED，而非 GUI PASS。新 workflow 仍须在远端运行；Linux 桌面分发继续停用 |

浏览器 endpoint/origin 配置保存、刷新、错误保留草稿、清除已通过真实打包 UI；不自动启动 Runtime/浏览器/helper、不读取个人浏览器 profile。前端只构建一次，原生 jobs 下载相同产物；Rust 缓存提前到 Cargo/SEA 构建之前，通知缺失或签名失败阻止发布。

最终源码回归：308 项 Vitest、65 项 Node、36 项 Vue、2 项 Rust，共 411 项通过；`npm run check`、`npm audit`（0 漏洞）、actionlint、通知完整性与专项生命周期回归通过。最终 0.5.20 签名包的嵌入版本、服务启动/停止、Playwright/QuickJS 批量图像及独立读回、稳定签名要求均通过。本地源码测试使用独立 Dev helper；正式包使用 certificate 身份，二者不混用。

## 本轮真实失败与未验收项

### 公网网络受阻

独立 Cloudflare Quick Tunnel 分别尝试 HTTP/2 与 QUIC，生成临时 URL 后均未注册连接，失败后只清理本次实例：

- `lookup cfd-features.argotunnel.com on 198.18.0.2:53 ... timeout`
- 边缘连接 `ip=198.18.0.42`（代理 fake-IP）
- precheck: `TCP Connectivity ... status=fail` / `UDP Connectivity ... status=fail`
- `Timed out waiting for Cloudflare ... connection`

失败不是通过，也没有发布这个临时 URL。Provider 现在补充固定的 DNS/出站 7844 诊断，同时保留原始错误 cause，不把 token/log 原文放进错误文案。

**需要用户可用的真实 DNS/分流及 Tunnel 出站网络后，复跑下面的 Cloudflare 命令。** 本轮不修改用户代理、系统 DNS、常驻 cloudflared、Home 服务或账号配置。Named Cloudflare、FRP、ngrok、Tailscale 的真实账号/客户端联调仍未完成。

### 平台与分发

- Windows UIA/视觉输入、安装/静默升级及 PID-tree 清理的实机结果还没有；新增 Windows 原生 CI smoke 已接入，但未运行远端流水线。Mac Intel 本轮只检查依赖图，不冒充 Intel 执行结果。
- 正式 macOS 安装位置的更新切换、首次 Gatekeeper 行为仍需安装验收；当前证明的是同证书候选身份复用已有 TCC 授权及真实 AX 动作。
- 正向 macOS Screen Recording/视觉输入未验收；不为验证悄悄申请权限。
- 最终候选包的原生 GUI 重跑遇到锁屏（`CGSSessionScreenIsLocked=1`、前台 `com.apple.loginwindow`）。验收脚本现在先只读检查交互桌面，不在锁屏状态启动测试窗口/动作；待用户解锁后使用 `--require-desktop` 复跑。不把以前一次通过替代最后一次实机验收。
- 预编译 cloudflared 的转依赖、WASM 工具链及 native SDK 的完整分发审阅仍在 `reviewWarnings` 中；文件完整检查不等于法律审计完成。

## 回归入口

所有脚本只使用自有临时 workspace/profile/进程。`tests/` 继续忽略、不随 Git 分发；CI 依靠被追踪的 smoke 脚本，不依赖本地 tests。

```sh
npm run check
npm test
node node_modules/vitest/vitest.mjs run --config apps/web/tests/vitest.config.ts
npm audit --audit-level=high
npm run smoke:priority
npm run notices -- --strict

# 真实 ChatGPT CIMD + 隔离 loopback OAuth/MCP，不跟随回调
npm run smoke:live-network -- --run --provider=external

# 账户无关 Quick Tunnel；要求真实公网网络可达，不读取现有 Tunnel 密钥
npm run smoke:live-network -- --run --provider=cloudflare --protocol=http2
npm run smoke:live-network -- --run --provider=cloudflare --protocol=quic

# 已构建的 SEA + CI 单独安装的测试 Chromium；不随产品打包浏览器
node node_modules/playwright-core/cli.js install chromium
npm run smoke:platform

# 自有原生 GUI，必须使用已授权的新签名包，不弹授权、不操作个人 app
node scripts/smoke-native-desktop.mjs --run --require-desktop \
  --service-executable '/absolute/path/to/micromatrix-service'
```

本次发布路径：固定提交 → 新 SemVer tag → 远端完整三平台矩阵 → 签名/通知/升级附件检查 → 自动公开 Release。公网及目标客户端实机验收仍待补齐，不因 tag 或构建通过而记为完成；流水线失败不绕过门槛手动上传。
