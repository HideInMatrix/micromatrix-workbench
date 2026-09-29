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
- MCP：`http://127.0.0.1:8234/mcp`

`npm run dev` 只启动控制 API 和 MCP，不启动 Vite UI。Tauri 开发窗口使用：

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

审批发生在 `AgentTool.execute` 之前。会话授权在 Runtime 停止或重启时清空。Workspace 是 Pi tools 的默认工作目录，不是操作系统沙箱；Pi 支持绝对路径，`safe` 也不等于文件系统隔离。`dangerous` 只适用于操作系统层面已经隔离的环境。

## 网络 Provider

- `external`：不启动 Tunnel 进程，使用配置的 URL。
- `cloudflare`：Cloudflare Quick Tunnel 或 Named Tunnel。
- `ngrok`：临时域名或固定域名。
- `frp`：运行已有的 `frpc` 配置；需要填写公网 URL。
- `tailscale`：运行 Tailscale Funnel；需要填写 Funnel 公网 URL。

Provider 只发布本地 MCP origin，不参与工具执行。完整环境变量见 [`.env.example`](.env.example)。

## 构建

```bash
npm run build:service  # Node 可运行的单文件 CJS，内嵌静态 UI
npm run build:sidecar  # 当前平台的 Node SEA sidecar
npm run tauri:build    # Tauri 2 应用与安装包
```

主要产物：

- `dist/micromatrix-service.cjs`
- `src-tauri/binaries/micromatrix-service-<target-triple>`
- `src-tauri/target/release/bundle/`

UI 配置默认写入 `~/.micromatrix-pi-mcp/runtime.json`。关闭“保存敏感信息”后，OAuth 密码与 Tunnel Token 不写入磁盘。

开发约束见 [`docs/architecture.md`](docs/architecture.md)，第三方许可证见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。依赖版本以 `package.json`、`package-lock.json` 和 `src-tauri/Cargo.lock` 为准。
