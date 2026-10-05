# Architecture constraints

这些约束用于阻止代码重新退化成“两套 Agent”或把安全边界散落到 UI、Tunnel 和工具实现中。

## One brain

网页 AI 模型负责推理与 tool selection。本地 Runtime 不调用模型，只暴露和执行 Pi `AgentTool`。

## BodyPlugin owns execution capabilities

每项可执行能力必须由 Pi 扩展注册。内置能力由 `BodyPlugin` 提供，再通过 `createPiBodyExtension()` 安装；外部 MCP 和 Skills 分别拥有自己的扩展，不把业务执行写进 UI 或 HTTP adapter。

```text
BodyPlugin → Pi AgentTool → approval gate → MCP tool
           → Pi ExtensionAPI (optional)
```

MCP transport、Tunnel Provider 和 UI 不得实现文件、Shell 等业务工具。外部程序路径、版本检测和权限也应归属于使用它的插件，不建立全局“工具链”层。

### MCP 与 Skills 的扩展接入

用户添加的 MCP 服务与 Skills 必须接入 Pi 的扩展/资源体系，不复制 Python 版的执行引擎。UI 只管理配置和生命周期，公网 MCP adapter 只暴露已加载的 Pi 能力，不维护第二份工具或技能实现。

- **MCP 扩展**：通过 Pi `ExtensionFactory` / `ExtensionAPI` 注册；连接、工具发现和关闭由扩展拥有，发现的工具进入同一 Pi 工具集合。当前锁定的 `0.87.1` 没有 `registerMcpServer` API，兼容实现在 `plugins/mcp` 桥接扩展内使用官方 MCP Client，再通过 `pi.registerTool()` 注册。上游 main 已提供原生 `registerMcpServer`，不得未经版本升级与回归就在锁定版本上调用。
- **Skills 扩展**：导入或创建标准 `SKILL.md`，扩展用 `resources_discover` 提供 `skillPaths`，由 Pi resource loader 完成解析和诊断，不另造 Skill 格式。Skill 是资源而不是可执行 TypeScript 扩展；不得自动执行其中的脚本。由于推理端在网页 AI，Pi 已加载的技能还须经公网 MCP 提供发现与按需读取，不能只加载到本地却让网页 AI 无法访问。
- **单一来源**：桌面目录和公网能力目录从实际加载的 Pi 扩展、工具与资源生成。MCP 工具、Skill 读取以及 Skill 所需的后续工具调用沿用同一审批入口；对外部 MCP 不得仅凭其自报 `readOnlyHint` 自动放行。
- **手动启动**：保存或展示配置不连接外部 MCP、不启动 stdio 子进程；只有点击 Runtime 启动或显式连接测试才触发连接。连接测试必须有界并清理资源。停止、启动失败及退出时关闭扩展拥有的连接和进程。

`packages/pi-body/PiBodyHost` 使用官方 `DefaultResourceLoader` 加载产品拥有的工厂，`ExtensionRunner` 驱动 session_start、resources_discover、tool_call、tool_result 与 session_shutdown，`wrapRegisteredTools()` 生成对外执行工具。只构造离线、内存的模型注册上下文供 Pi API 使用，不启动 AgentSession、推理或模型网络请求。Daemon 停止状态的内置工具预览不是一个正在运行的扩展宿主；点击启动后才用 Pi 实际注册的工具替换预览。MCP 审批仍在 execute 之前；扩展 hook 若修改已经审批的参数，当前宿主拒绝调用，不执行未审阅的替代操作。每个调用独立计数扩展 handler 错误，避免并发调用相互污染。

外部 `tools/list_changed` 由桥接扩展重新发现并调用 `pi.registerTool()`；宿主在锁定版本的公开 LoadedExtension tool map 上移除不再存在的注册，官方 Runner 和 MCP projection 使用同一个来源，不积累不可见的旧注册。注册变更广播 MCP 通知并重置审批；adapter 在审批返回后再次验证工具对象未变。发现失败撤销该连接的工具，手动刷新恢复；断线不隐式重跑本地程序。公网 Streamable HTTP 提供认证的 GET 通知流，停止时先关闭流再释放 listener，连接上限 64。

当前边界：只加载产品内置工厂，不自动执行用户提供的任意 TypeScript；技能来源可通过 UI 导入标准资源。外部 MCP 支持本地密钥变量、CIMD-only/PKCE OAuth、远端目录通知及显式刷新；旧 SSE 和服务特有 OAuth / 预注册客户端表单不在当前接入范围。OAuth 只在明确登录时打开浏览器；回调 state/verifier 不落盘，外部凭证与本服务向网页客户端颁发的 OAuth token 不得混用。扩展并非操作系统沙箱，尤其 stdio 服务自身运行所拥有的操作系统权限；配置添加和点击测试是用户对启动该程序的明确操作，不代表后续外部工具自动获得权限。

### Computer Use 的能力边界

ASIL 风格服务是同一可执行文件的独立 stdio MCP 模式，通过现有 Pi MCP 扩展注册，不构造 Runtime/Tunnel 或本地模型。UI 预填配置不启动进程；读操作也不自动请求系统授权。适配器拥有结构化状态、语义动作、revision 校验和动作后验证，禁止任意 eval/坐标点击回退。统一 DesktopProxy 组合惰性 NativeDesktopChannel，由 OS descriptor 选择 macOS Swift/Accessibility 或 Windows C#/UI Automation helper；状态、动作校验、审批、过期/revision、回读及生命周期共用，不按系统复制执行引擎。JSON 适配遵循 Workspace 边界。Linux 客户端构建和更新目标暂停，纯 TS CI 的 Linux runner 不属于产品客户端。状态是模型的不可信输入，工具审批与 OS 授权独立；动作默认禁用，打开后仍遵循外部 MCP 审批策略。具体合同及限制见 [Computer Use](computer-use.md)。

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

对外 OAuth 只支持 URL-form client ID：专用 `CimdClientResolver` 获取公开元数据；没有动态注册 endpoint、opaque ID、注册 Map/落盘。CIMD 是客户端识别/发现机制，不替代用户密码、PKCE、resource 绑定或工具审批。采用精确字符串 ID/redirect 比较、公开客户端 `none` 认证；ChatGPT 的 plural auth-method 字段仅在显式包含 `none` 时协商，不假装验证 private_key_jwt，也不接受共享密钥或文档中的私钥。元数据变动不自动撤销已发 token；token/session 仍有原 TTL/停止失效语义。

元数据域名优先使用系统 DNS；仅 proxy fake-IP 回退固定 TLS-verified Cloudflare DoH（1.1.1.1），重新验证全部 A/AAAA 为公网再固定连接。普通内网/混入内网的响应不回退；TLS、拒绝重定向与总期限仍保留。DNS/HTTPS 可用性失败使用 temporarily_unavailable，不伪装为文档身份错误。远端文档 GET 使用原 Host/SNI + 已验证公网 DNS 地址固定连接，不受代理环境变量影响；拒绝 private/loopback/reserved/IPv4-mapped/transition 地址及 HTTP 重定向。10 秒总期限、5 KiB、8 并发、60 次/分钟未命中发现与 100 项缓存边界；缓存遵循 HTTP 控制/Age，并上限 300 秒，不用 stale/error 结果。授权 UI 显示文档域名和回调（本机回调额外警告），不加载远端图标。响应 issuer 参数与 discovery issuer 一致；现有公网 issuer/forwarded-header 信任策略仍需独立收口，不能把 CIMD 当成这一边界的修复。

`plugins/mcp` 外部 OAuth 客户端也只用 CIMD：配置稳定公开 HTTPS `clientMetadataUrl` 与准确的固定 `oauthRedirectUri`，缺少时仅拒绝登录/启动该连接，不拒绝读取旧配置。SDK provider 始终给出该 URL 身份，因此 DCR 注册分支不可达；验证服务 discovery 的 CIMD/S256/none，缺少能力直接终止，绝不回退注册。回调仅绑定配置里的 127.0.0.1 高位端口及路径，核验 state、PKCE 和服务声明支持的 iss；被占用时不自动换端口。托管文档由操作者负责，不能借用别人的身份；临时 Tunnel 不等于稳定客户端身份。对自身客户端文档不额外自动 fetch，但外部授权服务器必须获取并校验它。

旧本地客户端注册文件完全不读取/写入，不自动删除操作者磁盘数据；旧随机 ID 需要在网页客户端重建连接，DCR-only 客户端不兼容。外部凭证加载清除旧随机身份或共享密钥 OAuth 状态，但保留 Header/env 变量；身份/回调变更取消挂起授权并清除旧 token，不改 Runtime 密码。

Authorization codes、access tokens、refresh tokens 和工具会话审批仍只存在内存中，重启后失效；客户端使用原 CIMD URL 重新授权不会继承之前的工具审批。只有操作者明确开启本地敏感信息保存时，OAuth 密码和网络令牌才能写入 `0600` 配置文件。控制面更新密钥必须使用 `unchanged / set / clear` 三态协议，不能用空字符串同时表示“保留”和“删除”。Authorization Code 必须使用 PKCE S256，回调地址仍须与注册值精确匹配。

## Reproducible packaging

`build:service` 编译 TypeScript、构建 Vite、内嵌静态资源并生成单文件 CJS。`build:sidecar` 把它注入当前平台的 Node SEA。Tauri 以 external sidecar 启动服务，并在应用退出时终止它。

内嵌网页连接同源控制 API；Vite/Tauri 使用显式配置或默认的独立控制 API。Origin 许可由实际控制监听地址/端口决定，不能直接信任请求中的 Host。

Pi 包使用精确版本，不跟踪上游 `main`。升级必须重新运行类型、tool schema、审批和打包回归。

## External credentials and owned resources

MCP 凭证存储在 `<configFile>.mcp-credentials.json`，只在本地控制面写入，快照仅含变量名与授权状态。目标 ID/transport/URL/程序参数指纹绑定凭证；清理已移除/替换连接的记录。文件有大小/字段限制与 `0600` 原子替换，遵循 rememberSecrets，但不冒充操作系统加密 keychain。

stdio 使用 SDK 的 framing 和 Client，transport 专门拥有启动程序的进程组：Unix 对 owned group 有界 TERM/KILL；Windows 通过 cross-spawn 解析程序，再按 owned PID `taskkill /T /F`。不按镜像名终止其他进程；主动脱离进程组或 Windows breakaway 的服务不属于此保障，也不是沙箱。多个 MCP 连接并行关闭，Pi 的 session_shutdown 仍驱动扩展生命周期。

Skill 编辑仅允许已配置资源的准确 ID，保存前后核验 revision，并由 Pi 验证候选文档后原子替换。支持文件按已发现 Skill root 解析，只读有界 UTF-8 普通文件；对本机恶意代码的 filesystem race 仍需 OS 沙箱，不承诺仅凭路径检查实现进程隔离。

Tauri 正常退出通过 native cleanup 请求 PID 匹配的控制服务停止 Runtime，再终止 sidecar；更新器的资源释放路径也使用同一清理函数。失败和超时保留有界强制退出，不伪装为已完成所有 Provider 的清理。默认仍不启动 Runtime。
