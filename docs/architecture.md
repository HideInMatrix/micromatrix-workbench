# Architecture constraints

这些约束用于阻止代码重新退化成“两套 Agent”或把安全边界散落到 UI、Tunnel 和工具实现中。

## One brain

网页 AI 模型负责推理与 tool selection。本地 Runtime 不调用模型，只暴露和执行 Pi `AgentTool`。

## BodyPlugin owns execution capabilities

每项本地能力必须由 `BodyPlugin` 提供。插件创建 Pi tools，并可通过 Pi `ExtensionAPI` 安装生命周期行为。

```text
BodyPlugin → Pi AgentTool → approval gate → MCP tool
           → Pi ExtensionAPI (optional)
```

MCP transport、Tunnel Provider 和 UI 不得实现文件、Shell 等业务工具。外部程序路径、版本检测和权限也应归属于使用它的插件，不建立全局“工具链”层。

## Approval before execution

MCP adapter 必须先调用 approval policy，再调用 `AgentTool.execute`。审批只允许本次调用或当前认证客户端会话；会话授权键必须包含 OAuth authorization grant session，不能只按 permission 全局缓存。refresh token 轮换保持原 session，Runtime 停止时清空全部授权。传给 UI 的敏感参数必须递归脱敏。

Workspace Tools 必须在 BodyPlugin 的 operations 层执行 canonical boundary 检查，拒绝指向外部的绝对路径、`..`、symlink 和 junction 逃逸。路径检查不能散落到 UI 或 MCP transport。

这不是进程级沙箱：Shell Tool 不受 Workspace 路径边界约束，独立本地进程也可能制造 TOCTOU filesystem race。需要对抗本机恶意代码时必须使用容器或操作系统沙箱，不能靠审批模式暗示隔离已经存在。

## Separate control and data planes

- `/mcp` 是网页 AI 客户端使用的数据面。
- loopback control API 是 Vite/Tauri 使用的控制面，负责配置和 Runtime 生命周期。
- 一个桌面实例只管理一个 Runtime。

应用启动只启动控制面并读取配置，不构造或启动 Tunnel。只有显式 `start_runtime` 才运行 MCP 和 Provider；旧 auto-start 配置不再生效。Runtime 配置与插件切换先构建、验证并持久化候选资源，成功后才替换原配置和 registry；失败保留原状态。启停与配置变更必须串行化。

控制面必须监听回环地址。MCP 默认监听回环地址；任何非回环监听或公网 Tunnel 都必须配置 OAuth 或兼容 Bearer Token。

## Network providers do not execute tools

External、Cloudflare、ngrok、FRP 和 Tailscale Provider 只把本地 MCP origin 发布出去，不解析 MCP 请求，也不执行工具。

## Secrets and OAuth state

DCR clients、authorization codes、access tokens 和 refresh tokens 只存在内存中。只有操作者明确开启本地敏感信息保存时，OAuth 密码和网络令牌才能写入 `0600` 配置文件。控制面更新密钥必须使用 `unchanged / set / clear` 三态协议，不能用空字符串同时表示“保留”和“删除”。Authorization Code 必须使用 PKCE S256。

## Reproducible packaging

`build:service` 编译 TypeScript、构建 Vite、内嵌静态资源并生成单文件 CJS。`build:sidecar` 把它注入当前平台的 Node SEA。Tauri 以 external sidecar 启动服务，并在应用退出时终止它。

内嵌网页连接同源控制 API；Vite/Tauri 使用显式配置或默认的独立控制 API。Origin 许可由实际控制监听地址/端口决定，不能直接信任请求中的 Host。

Pi 包使用精确版本，不跟踪上游 `main`。升级必须重新运行类型、tool schema、审批和打包回归。
