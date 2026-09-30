# MicroMatrix Pi MCP Agent

把网页 AI 模型作为推理端，把 Pi 工具作为本地执行端：

```text
Web AI → OAuth MCP → approval policy → Pi BodyPlugin → local workspace
```

本地服务不运行第二个模型循环。当前 BodyPlugin 提供 Workspace Tools（必需）和 Shell Tool（可选）；网络层支持 External、Cloudflare、ngrok、FRP 与 Tailscale Funnel。

## 开发运行

要求：Node.js `>=22.19`。运行 Tauri 还需要 Rust `>=1.90`。

```bash
npm install
cp .env.example .env.local
npm run check
npm run dev:desktop
```

`dev:desktop` 同时启动：

- Vite UI：`http://127.0.0.1:5173`
- 本地控制 API：`http://127.0.0.1:8233`
- MCP：点击 UI 的“启动”后才监听 `http://127.0.0.1:8234/mcp`

应用启动只加载配置并启动控制 API，**不会自动运行 Runtime 或 Tunnel**。旧配置的 `enabled` 和旧环境变量 `MICROMATRIX_ENABLED` 不再生效；未完成的 Tunnel 配置不会在打开应用时执行或反复报错。配置保存失败会保留原配置和工具；启动失败不会清空工具。

`npm run dev` 只启动控制 API，不启动 Vite UI 或 MCP。Tauri 开发窗口使用：

```bash
npm run tauri:dev
```

## MCP 认证

本机回环地址可以无认证运行。需要通过 Tunnel 或非回环地址公开时，必须配置以下任一项，否则 Runtime 拒绝启动：

- `MICROMATRIX_OAUTH_PASSWORD`：供网页 MCP 客户端使用的 OAuth 2.0 + DCR + PKCE 流程。
- `MICROMATRIX_AUTH_TOKEN`：兼容旧客户端的静态 Bearer Token。

客户端连接地址为 `https://<public-host>/mcp`。OAuth client、authorization code 和 token 只保存在进程内存中，Runtime 重启后失效。

## 执行审批

| 模式 | `read/grep/find/ls` | `edit/write` | `bash` / 未知工具 |
| --- | --- | --- | --- |
| `safe` | 自动允许 | 本地审批 | 本地审批 |
| `trusted` | 自动允许 | 自动允许 | 本地审批 |
| `dangerous` | 自动允许 | 自动允许 | 自动允许 |

审批发生在 `AgentTool.execute` 之前。“本次客户端会话允许”按 OAuth authorization grant 隔离；refresh token 轮换保持同一会话，但其他客户端或新的授权会话不会继承。Runtime 停止、重启或权限模式变化时清空全部会话授权。Workspace Tools 会对路径和文件操作执行 canonical boundary 检查，拒绝指向 Workspace 外部的绝对路径、`..` 和 symlink/junction；Workspace 内部的绝对路径仍可使用。

静态 Bearer Token 本身没有客户端身份，因此持有同一个静态 Token 的请求共享审批会话；需要严格客户端隔离时使用 OAuth。

这层边界只覆盖 Workspace Tools，不是操作系统沙箱。可选 Shell Tool 仍能访问 Runtime 进程拥有权限的路径，并且独立本地进程可以制造 filesystem race；需要对抗本机恶意代码时必须使用容器或操作系统沙箱。`dangerous` 只适用于已经隔离的环境。

## 网络 Provider

- `external`：不启动 Tunnel 进程，使用配置的 URL。
- `cloudflare`：Cloudflare Quick Tunnel 或 Named Tunnel。
- `ngrok`：临时域名或固定域名。
- `frp`：运行已有的 `frpc` 配置；需要填写公网 URL。
- `tailscale`：运行 Tailscale Funnel；需要填写 Funnel 公网 URL。

Provider 只发布本地 MCP origin，不参与工具执行。完整环境变量见 [`.env.example`](.env.example)。
点击启动 Runtime 后会检查 Workspace、认证、Tunnel executable 与 FRP 配置文件；Cloudflare、ngrok 或 FRP 进程异常退出时，Runtime 会关闭 MCP、清空已发布地址并在 UI 显示退出原因。

## 构建

```bash
npm run build:service  # Node 可运行的单文件 CJS，内嵌静态 UI
npm run build:sidecar  # 当前平台的 Node SEA sidecar
npm run check:sidecar  # 重建并验证健康检查、内嵌 UI/API 与退出清理
npm run tauri:build    # Tauri 2 应用与安装包
```

主要产物：

- `dist/micromatrix-service.cjs`
- `src-tauri/binaries/micromatrix-service-<target-triple>`
- `src-tauri/target/release/bundle/`

UI 配置默认写入 `~/.micromatrix-pi-mcp/runtime.json`。关闭“保存敏感信息”后，OAuth 密码和网络令牌不写入磁盘。密码框留空表示保留现有值；只有点击对应的清除按钮并保存才会删除已有密钥。

单文件服务上的内嵌 Web UI 使用页面自己的 origin，可使用自定义控制端口；Vite/Tauri 默认连接 `http://127.0.0.1:8233`，如需自定义应在构建前设置 `VITE_CONTROL_URL`。

## GitHub Actions 打包

- 分支 push / PR：`CI` 自动运行版本一致性检查、类型检查、测试和 Web 构建。
- 手动运行 `Desktop packages`：回归后构建 macOS arm64/x64、Windows x64、Linux x64 的实验性安装包，下载入口为该次运行的 **Artifacts**。
- 推送 `v*` tag：执行同样的打包流程；全部平台成功后创建 **Draft + Pre-release**，不自动公开发布。任意平台失败不会创建 Release。

提交当前实现、测试、脚本和 `.github` 后推送分支，再推送测试 tag，例如：

```bash
git push origin master
git tag v0.5.0-alpha.1
git push origin v0.5.0-alpha.1
```

这些命令要求修改已经提交；不要把 tag 打在旧提交上。当前应用版本为 `0.5.0`，接受 `v0.5.0` 或 `v0.5.0-alpha/beta/rc.N` 标签。预发布标签只标识测试构建，**不会自动修改应用内版本号**；完整 tag、commit 和构建平台记录在 `build-*.json`。改变核心版本前须同步 `package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、`src-tauri/Cargo.lock` 及应用显示版本。

旧 tag 的失败运行重新执行仍使用旧提交，不会自动读取 master 上的修复。提交并推送修复后，可手动选择 master 打包，或推送指向修复提交的新测试 tag；不要为重试擅自覆盖已存在的 tag。

手动触发需要 workflow 文件已经存在于仓库默认分支，随后可在 Run workflow 选择当前开发分支；尚未合并时可先使用 tag 自动触发。Actions 必须启用且允许工作流中使用的固定提交 Actions。checkout/setup-node/upload/download 已使用 Node 24 运行时版本，项目测试与 SEA 构建的 Node 版本仍固定为 22.23.3；两者不是同一个配置。默认使用内置 `GITHUB_TOKEN`，无需提供个人 Token 或生产签名密钥；只有创建 Release 草稿的 job 获得 `contents: write`。

产物包含安装包、独立服务压缩包、已列出的许可证通知、构建元数据和 `SHA256SUMS-*.txt`。macOS 使用 ad-hoc 签名、没有公证；Windows 未进行 Authenticode 签名。编译通过不是平台安装验收，当前仍是测试包；首次远端运行前不宣称四个平台均已验证。流水线依据 [Tauri 打包指南](https://v2.tauri.app/distribute/pipelines/github/)、[GitHub 手动触发要求](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)和 [Node SEA 构建流程](https://nodejs.org/download/release/latest-v22.x/docs/api/single-executable-applications.html)。

开发约束见 [`docs/architecture.md`](docs/architecture.md)，第三方许可证见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。依赖版本以 `package.json`、`package-lock.json` 和 `src-tauri/Cargo.lock` 为准。
