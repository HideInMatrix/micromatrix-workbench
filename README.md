# MicroMatrix Pi MCP Agent

以 Pi `AgentTool` / Extension 为本地执行身体、网页 AI 模型为推理大脑的 MCP 服务。核心代码使用 TypeScript 7，控制台使用 Vite 8 + Vue，桌面壳使用 Tauri 2。

## 当前能力

- Streamable HTTP MCP：`/mcp`
- OAuth 2.0：Protected Resource Metadata、Authorization Server Metadata、DCR、Authorization Code + PKCE、Refresh Token、Revocation
- 本地审批策略：`safe` / `trusted` / `dangerous`，支持单次与会话授权，敏感参数脱敏
- Pi 功能插件：必需的 Workspace Tools、可选 Shell Tool
- 网络 Provider：External URL、Cloudflare Tunnel、ngrok、FRP、Tailscale Funnel
- 本地控制面：服务状态、插件开关、OAuth、审批模式、Tunnel 配置和日志
- 发布形式：内嵌静态 Web 的单文件 Node SEA 服务，以及携带该 sidecar 的 Tauri 2 应用

远端模型只负责推理和 MCP tool selection；本地进程不再运行第二套 LLM loop。

## 版本

- Node.js `>=22.19`
- TypeScript `7.0.2`
- Vite `8.3.1`
- Tauri `2.12.0`
- Pi `0.87.1`
- MCP TypeScript SDK `1.30.1`

## 开发

```bash
cp .env.example .env.local
npm install --ignore-scripts
npm run check
```

只启动本地服务：

```bash
npm run dev
# 控制台：http://127.0.0.1:8233
# MCP：http://127.0.0.1:8234/mcp
```

启动 Vite 控制台和本地服务：

```bash
npm run dev:desktop
```

启动 Tauri 2 开发窗口（需 Rust stable）：

```bash
npm run tauri:dev
```

## OAuth 接入网页 MCP 客户端

在 UI 或 `.env.local` 中设置 `MICROMATRIX_OAUTH_PASSWORD`。客户端连接公开的 `https://<host>/mcp` 后会按标准发现：

- `/.well-known/oauth-protected-resource/mcp`
- `/.well-known/oauth-authorization-server`
- `/register`
- `/authorize`
- `/token`
- `/revoke`

实现只接受 PKCE `S256`。DCR client、authorization code 和 token 当前保存在进程内存中，服务重启后失效。公网 Tunnel 若既未配置 OAuth 密码，也未配置静态 `MICROMATRIX_AUTH_TOKEN`，Runtime 会拒绝启动。

## 审批模式

| 模式 | 只读 Workspace | Workspace 写入 | Shell / 未知工具 |
| --- | --- | --- | --- |
| `safe` | 自动允许 | 本地弹窗审批 | 本地弹窗审批 |
| `trusted` | 自动允许 | 自动允许 | 本地弹窗审批 |
| `dangerous` | 自动允许 | 自动允许 | 自动允许 |

审批发生在 Pi tool 真正执行之前。`dangerous` 只应在隔离且可信的 Workspace 中使用。

## Tunnel Provider

- `external`：不启动子进程，直接发布配置的 URL；默认仅本机地址。
- `cloudflare`：Quick Tunnel 或 Named Tunnel。
- `ngrok`：可使用临时域名或配置固定公网 URL。
- `frp`：运行现有 `frpc` 配置文件，必须提供公网 URL。
- `tailscale`：通过 `tailscale funnel --bg --yes` 发布，必须提供 Funnel 公网 URL。

网络 Provider 只负责暴露本地服务，不参与 MCP tool 执行。

## 构建与打包

```bash
# Vite 静态资源 + daemon 打成可直接运行的 CJS 服务包
npm run build:service

# 当前平台 Node SEA，可作为 Tauri externalBin
npm run build:sidecar

# Tauri 2 安装包/应用
npm run tauri:build
```

产物：

- `dist/micromatrix-service.cjs`
- `src-tauri/binaries/micromatrix-service-<target-triple>`（生成文件，不提交）
- `src-tauri/target/release/bundle/`

## 配置持久化

UI 保存到 `~/.micromatrix-pi-mcp/runtime.json`，或由 `MICROMATRIX_CONFIG_FILE` 改写路径。文件以 `0600` 原子写入；关闭“保存敏感信息”后，不持久化 OAuth 密码和 Token。环境变量优先于磁盘配置。

架构边界和决策见 [`docs/architecture.md`](docs/architecture.md)。
