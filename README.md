# micromatrix agent

把网页 AI 模型作为推理端，把 Pi 工具作为本地执行端：

```text
Web AI → OAuth MCP → approval policy → Pi BodyPlugin → local workspace
```

本地服务不运行第二个模型循环。Pi 扩展宿主提供 Workspace Tools（必需）、Shell Tool（可选）、外部 MCP 桥接和 Skills 资源；网络层支持 External、Cloudflare、ngrok、FRP 与 Tailscale Funnel。

## 添加 MCP 与 Skills

插件页面提供“添加 MCP / 添加 Skill”。它只保存配置；Runtime 点击启动后，官方 Pi `ExtensionFactory`、`ExtensionRunner` 和 `DefaultResourceLoader` 才加载能力，不自动执行 Workspace 中的未知扩展代码。

- **MCP**：配置 stdio 的可执行程序与参数 JSON 数组，或 Streamable HTTP 的 `/mcp` 地址。测试连接仅执行握手和工具发现，结束后关闭连接，不调用工具。启用服务通过 Pi 扩展注册为 `mcp__<id>__<tool>_<hash>`，名称不与内置工具冲突。编辑、启停和移除需要先停止 Runtime。
- **Skills**：导入本地目录 / `SKILL.md` 的绝对路径，或在界面填写名称、描述和方法说明创建标准 `SKILL.md`。Pi `resources_discover` 提供路径，由 Pi 解析与校验；网页 AI 用 `skills_list` / `skills_read` 按需读取，不运行本地模型循环，也不自动执行 Skill 内的脚本。移除来源只解除引用，不删除用户文件；可打开完整文档编辑，使用 revision 防止覆盖并发改动；修改后 stop/start 重新加载。网页 AI 还可用 `skills_files` / `skills_file_read` 读取 Skill 目录内的 UTF-8 支持文件（最大 256 KB），拒绝绝对路径、越界和符号链接。
- **审批与清理**：外部 MCP 工具和 Skill 读取沿用审批，不能凭外部服务自报 `readOnlyHint` 自动批准。Runtime 停止、启动失败或 Tunnel 异常会关闭扩展连接和 owned stdio 进程树。支持远端 `tools/list_changed` 和界面“刷新工具”，同步增加、替换和删除 Pi 工具；变更撤销旧审批，待审批调用不得执行被替换的定义。发现失败撤销旧工具；断线后停止再启动以重连。

认证配置保存变量引用，真实值可在界面填写本地密钥，也可来自服务环境：stdio `envRefs` 示例 `{"API_KEY":"MY_API_KEY"}`，HTTP headers 示例 `{"Authorization":"Bearer ${MY_TOKEN}"}`。本地填写值优先，空白保留已有值，清除按钮显式删除；保存后编辑表单不清空。不要把密钥写入 command / args。HTTP 可选择 OAuth：先保存连接，再点击“授权登录”，桌面通过系统浏览器打开授权，浏览器版需允许弹窗；标准 SDK 负责 discovery、CIMD 身份、PKCE 和 token refresh，本地固定端口回调校验 state 与服务声明的 issuer。只有显式登录打开浏览器，取消、超时、停止和退出会关闭回调监听。OAuth 仅支持声明 CIMD / S256 / none 的服务，不回退 DCR。必须填写自己的公网 HTTPS `clientMetadataUrl` 和文档中登记的固定 `oauthRedirectUri`（`http://127.0.0.1:空闲端口/路径`，端口 >= 1024）；缺少时可编辑旧配置，登录明确报错。未实现服务特有登录或预注册客户端表单。HTTP 使用 HTTPS，回环地址可使用 HTTP；旧 SSE 不支持。stdio 依赖相应外部程序已安装，安装包不会代装所有 Node/Python MCP 服务。

配置保存在 Runtime 配置的 `extensions` 中；创建的 Skill 文件位于配置目录下的 `skills/<id>/SKILL.md`。Skills 的支持文件保持原样，只提供按 Skill ID + 相对路径的读取；执行支持脚本仍要调用受审批的工具，并受对应工具的路径边界约束。MCP 密钥和外部 OAuth token 单独保存在 `<configFile>.mcp-credentials.json`（Unix `0600`，最大 2 MB），绑定服务 ID 和目标 URL/程序参数；修改目标不会复用旧凭证。遵循 Runtime 的“在本机保存秘密”开关，关闭后删除落盘副本，但本次服务会话可继续使用内存凭证。这不是加密 keychain，也不通过 HTTP/MCP 导出明文。

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

桌面 UI 会先等待控制服务就绪，再加载配置；这不是启动 MCP 或 Tunnel。sidecar 无法启动或退出时，页面显示具体诊断和“重新加载配置”，不再只显示 `Load failed` 或无限等待。软件名为 `micromatrix agent`；桌面 PNG/ICO/ICNS 使用旧版提供的原图标，侧栏标识保持不变。为保留现有配置，应用 identifier 与配置目录不改名。

SEA 中 Pi 的资源目录默认固定在可执行文件所在目录，不向上扫描源码目录寻找 `package.json`；避免尚未点击启动就触发工作目录/Documents 的读取授权。显式配置的 `PI_PACKAGE_DIR` 仍保留。

`npm run dev` 只启动控制 API，不启动 Vite UI 或 MCP。Tauri 开发窗口使用：

```bash
npm run tauri:dev
```

所有 `tests/` 目录仅保留本地，Git 不再跟踪；新克隆不包含测试文件。`npm run check` 只做类型检查和 Web 构建，保留测试文件的开发机可以另跑 `npm test`。远端 CI 不再提供这些单元/集成测试的回归保障，桌面打包仍执行 SEA 冒烟检查。

## MCP 认证

本机回环地址可以无认证运行。需要通过 Tunnel 或非回环地址公开时，必须配置以下任一项，否则 Runtime 拒绝启动：

- `MICROMATRIX_OAUTH_PASSWORD`：供网页 MCP 客户端使用的 OAuth Authorization Code + PKCE 流程；仅支持 CIMD，不再提供 DCR。
- `MICROMATRIX_AUTH_TOKEN`：兼容旧客户端的静态 Bearer Token。

客户端连接地址为 `https://<public-host>/mcp`。授权服务器 metadata 声明 `client_id_metadata_document_supported: true`，客户端必须使用公开 HTTPS JSON 文档 URL 作为 client ID；`/register` 和 `registration_endpoint` 已移除。服务核验文档 `client_id` 与请求值完全相同、有效名称及精确回调地址；只协商 `none` 公共客户端认证，仍必须验证密码和 PKCE，不支持只提供 `private_key_jwt` 的客户端。授权页显示元数据域名与回调地址，并提示回环回调的身份风险；授权重定向成功/错误响应都带 `iss`，与 discovery 中的 issuer 一致。

CIMD 文档只作有界内存缓存，不使用本地客户端注册文件；只允许标准 HTTPS 端口和非根文档路径，不接受 query、userinfo、fragment 或 dot path。不跟随重定向，不下载文档里的 logo/JWKS；DNS 所有地址必须是公网地址，连接使用已校验地址固定 DNS，保留 TLS/Host 校验。单次 DNS/HTTP 总期限 10 秒、JSON 最大 5 KiB、最多 8 个并行发现、每分钟最多 60 次未命中发现、缓存最多 100 项且不超过 5 分钟，尊重 no-store/no-cache/Age。发现失败不会回退到未验证或过期文档。如果代理 fake-IP DNS 返回 `198.18.x.x`、内网或保留地址，会拒绝；需要在代理/DNS 侧让客户端元数据域名解析为真实公网地址，不应关闭 SSRF 防护。

旧 DCR 的随机 client ID 不再接受，客户端需更新为 CIMD 或删除旧连接后重建；仅支持 DCR 的客户端无法连接。旧 `<configFile>.oauth-clients.json` 不再读取/写入，损坏的旧文件不影响启动；不自动删除用户磁盘上的旧数据，可自行清理。授权码、access/refresh token 和工具审批仍只存在内存，重启后按文档 URL 重新授权，不继承旧工具审批。密码、Bearer Token、Tunnel 配置与“手动启动”语义不变。

外部 MCP 的 CIMD 文档示例（自己控制的 HTTPS 站点托管，服务端必须可读取）：

```json
{
  "client_id": "https://your-domain.example/oauth/client.json",
  "client_name": "micromatrix agent",
  "redirect_uris": ["http://127.0.0.1:18456/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none"
}
```

在 MCP 编辑器填入同一文档 URL 与准确回调后保存，再点击授权登录。端口被占用会报错，不随机换端口破坏文档登记；临时 Tunnel 地址不是稳定客户端身份，也不会在保存时启动服务来托管文档。不能借用 ChatGPT/其他应用的 CIMD URL。修改文档身份或回调会取消挂起授权、丢弃该外部服务的旧 OAuth token；已有本地 Header 密钥保留。未发布任何公共元数据文档，也没有假定部署域名。

Runtime 启动后，浏览器访问公网域名根路径 `/` 会返回 JSON 服务信息：应用名称/版本、支持的 MCP 协议、`/mcp` 端点、认证方式和当前工具名称/数量。此信息无需认证，但不包含工作目录、配置或密钥，也不是本地管理页面；MCP 调用仍按配置认证和审批。端点使用相对路径，兼容 Cloudflare 随机域名与固定域名。

## 执行审批

| 模式 | `read/grep/find/ls` | `edit/write` | `bash` / 未知工具 |
| --- | --- | --- | --- |
| `safe` | 自动允许 | 本地审批 | 本地审批 |
| `trusted` | 自动允许 | 自动允许 | 本地审批 |
| `dangerous` | 自动允许 | 自动允许 | 自动允许 |

审批发生在 `AgentTool.execute` 之前。“本次客户端会话允许”按 OAuth authorization grant 隔离；refresh token 轮换保持同一会话，但其他客户端或新的授权会话不会继承。Runtime 停止、重启、权限模式或外部工具定义变化时清空全部会话授权。Workspace Tools 会对路径和文件操作执行 canonical boundary 检查，拒绝指向 Workspace 外部的绝对路径、`..` 和 symlink/junction；Workspace 内部的绝对路径仍可使用。

静态 Bearer Token 本身没有客户端身份，因此持有同一个静态 Token 的请求共享审批会话；需要严格客户端隔离时使用 OAuth。

这层边界只覆盖 Workspace Tools，不是操作系统沙箱。可选 Shell Tool 仍能访问 Runtime 进程拥有权限的路径，并且独立本地进程可以制造 filesystem race；需要对抗本机恶意代码时必须使用容器或操作系统沙箱。`dangerous` 只适用于已经隔离的环境。

## 网络 Provider

- `external`：不启动 Tunnel 进程，使用配置的 URL。
- `cloudflare`：Cloudflare Quick Tunnel 或 Named Tunnel。
- `ngrok`：临时域名或固定域名。
- `frp`：运行已有的 `frpc` 配置；需要填写公网 URL。
- `tailscale`：运行 Tailscale Funnel；需要填写 Funnel 公网 URL。

Provider 只发布本地 MCP origin，不参与工具执行。完整环境变量见 [`.env.example`](.env.example)。
Cloudflare 的“隧道传输协议”可选自动（默认）、HTTP/2（TCP）或 QUIC（UDP），Quick / Named Tunnel 均使用所选值；需要先停止 Runtime 才能修改，保存后不会自动启动。`MICROMATRIX_CLOUDFLARE_PROTOCOL` 可覆盖磁盘配置；未配置的旧版配置继续使用 `auto`。这控制 cloudflared 到 Cloudflare 的连接，不是把 MCP 改为 UDP；UDP 出站受限时可选择 HTTP/2。[官方传输参数与端口](https://developers.cloudflare.com/tunnel/configuration/)。
点击启动 Runtime 后会检查 Workspace、认证、Tunnel executable 与 FRP 配置文件；Cloudflare、ngrok 或 FRP 进程异常退出时，Runtime 会关闭 MCP、清空已发布地址并在 UI 显示退出原因。

桌面安装包内置 `cloudflared 2026.9.3`，Cloudflare 表单不再提供程序路径输入，默认使用包内程序，不依赖 Homebrew、系统 PATH 或另行安装。只在点击启动且选择 Cloudflare 后运行隧道。源码开发默认使用 PATH 上的 `cloudflared`，高级环境变量/API 路径覆盖仍保留；ngrok、FRP、Tailscale 仍需安装并配置各自客户端。

`npm run build:sidecar` 自动下载对应平台的官方 cloudflared 固定版本，按 `scripts/cloudflared-manifest.json` 的 SHA-256 校验，缓存到 `.cache/cloudflared/`；下载、摘要或版本检查失败会阻止打包。`--version` 冒烟不连接公网，最终 macOS 包另检查重签名后的 cloudflared 和 Node sidecar；Apache-2.0 许可证随安装包资源交付。[官方固定版本](https://github.com/cloudflare/cloudflared/releases/tag/2026.9.3)。

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

GitHub macOS 打包先由 Tauri 构建/签名 `.app`，再运行 `node scripts/package-macos-dmg.mjs` 单独生成压缩、只读 DMG；不依赖 Finder/AppleScript 或可写镜像的挂载/缩容。原图标、签名和两项 sidecar 随 `.app` 原样复制，带 `/Applications` 拖拽安装链接。仅对磁盘镜像的明确临时忙碌错误最多尝试三次，不重编译 Rust/Vite；校验失败阻止发布。详细日志位于 `src-tauri/target/packaging-logs/create-dmg.log`，Actions 无论成功/失败均尝试上传 `packaging-logs-macos-*` 诊断附件。此路径适用于目前的实验性 ad-hoc 包，不代表已完成生产签名/公证；本地 `tauri:build` 仍走 Tauri 默认完整打包。

UI 配置默认写入 `~/.micromatrix-pi-mcp/runtime.json`。关闭“保存敏感信息”后，OAuth 密码和网络令牌不写入磁盘。密钥输入在保存、启停和页面切换后保留在界面内，默认以密码掩码显示，眼睛按钮可查看。Tauri 重启后通过原生桥回填已保存的密钥，不新增返回密钥的 HTTP/MCP 接口；关闭保存后仅保留在当前界面会话，退出后需重新输入。浏览器版不从服务回读明文；已有值仍由服务保留。只有点击清除按钮并保存才删除已有密钥。

界面掩码不是磁盘加密：选择保存时，密钥仍在本机 JSON 配置内（Unix 文件权限 `0600`）。

控制面校验回环 Host / 端口及 Origin，修改请求必须使用 `application/json`，拒绝未授权跨站请求（保留 Vite/Tauri 的受信 Origin）；不代表对本机恶意进程提供隔离。桌面正常退出先核验 sidecar PID 并请求停止 Runtime，最多等待 6 秒后终止 owned sidecar；不停止占用同端口的其他服务。

单文件服务上的内嵌 Web UI 使用页面自己的 origin，可使用自定义控制端口；Vite/Tauri 默认连接 `http://127.0.0.1:8233`，如需自定义应在构建前设置 `VITE_CONTROL_URL`。

### 工具审批排查

Shell 插件向 MCP 暴露的工具名是 `bash`。`safe` 和 `trusted` 模式的 Shell 调用都需批准；`trusted` 仅自动批准 Workspace 写入，不自动批准 Shell。待审批时桌面弹窗会提醒并激活窗口；仅在用户批准后执行。运行日志会区分 `queued`、`allowed`、`denied`、`timed_out`、`cancelled`、`stopped`，不记录完整命令或密钥。超时/客户端取消不再冒充用户拒绝。若模型称“没有权限”却没有 `queued` 日志，应检查其实际工具错误与 `tools/list`，不能把模型的总结当作已经到达本服务的证据；客户端自身的权限限制不由本应用审批控制。

## GitHub Actions 打包

- 分支 push / PR：`CI` 自动准备应用版本、运行类型检查和 Web 构建。
- 手动运行 `Desktop packages`：检查后构建 macOS arm64/x64、Windows x64、Linux x64 的实验性安装包，并执行各平台 SEA 冒烟；下载入口为该次运行的 **Artifacts**。
- 推送 `v*` tag：执行同样的打包流程；全部平台成功后，只选择 6 个桌面安装包，验证各平台 SHA-256 并合并为 `SHA256SUMS.txt`，上传完成后自动公开为正式 **Release / Latest**（如 `v0.5.9`）。显式 `-rc` / `-beta` tag 保持 Pre-release，避免进入正式渠道。独立服务、构建 JSON 和单独通知文件不上传 Release。任意平台失败不会进入发布；上传失败保留草稿，不公开不完整的版本。无需手动点击 Publish；签名更新包供桌面应用自动下载安装。

提交当前实现、脚本和 `.github` 后推送分支，再推送一个未使用的 tag，例如：

```bash
git push origin master
git tag v0.5.3
git push origin v0.5.3
```

这些命令要求修改已经提交；不要把 tag 打在旧提交上。**发布版本以 tag 为准，不再要求手动修改多处版本文件**。例如 `v0.5.2` 构建为 `0.5.2`，`v0.6.0-rc.1` 构建为 `0.6.0-rc.1`，不必与源码当前的 `0.5.0` 相等。

`git tag` 本身只创建引用，不修改文件。Actions 根据 `GITHUB_REF_TYPE=tag` 和 `GITHUB_REF_NAME`，在每个构建 job 执行 `scripts/release-version.mjs`，自动同步根 `package.json`、npm 锁文件、Tauri 配置、Cargo 配置/锁文件和应用显示版本；只修改构建工作区，不自动提交回仓库，不改内部插件/依赖版本。完整 tag、commit 和构建平台记录在 `build-*.json`。GitHub 非 tag 构建使用根 `package.json` 的版本；本地 `tauri:dev` / `tauri:build` 自动读取当前 HEAD 可达的最新 SemVer tag 并同步版本，没有可用 tag 时使用 `package.json`。桌面“关于”读取 Tauri 原生版本，不依赖控制服务的版本或就绪状态。正在运行的旧程序不会因源码变化自动变成新版，必须重建并重新启动。[GitHub 提供的引用变量](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)。

只保留 `v` + SemVer 格式校验（如 `v1.2.3`、`v1.2.3-beta.1`）；任意字符串不能作为 npm/Cargo/Tauri 应用版本。安装包、服务和显示版本需要一致，但一致性由构建脚本自动生成，而非人工维护。

旧 tag 的失败运行重新执行仍使用旧提交，不会自动读取 master 上的修复。提交并推送修复后，可手动选择 master 打包，或推送指向修复提交的新测试 tag；不要为重试擅自覆盖已存在的 tag。

旧流程只保存 Release 草稿，且附件包含独立服务和审计文件。新流程自动发布精简附件，但不会重写已有公开版本；已有附件不会因修改 workflow 自动消失。已有草稿若包含白名单外附件，新流程拒绝公开，须先手动清理或使用新 tag。

手动触发需要 workflow 文件已经存在于仓库默认分支，随后可在 Run workflow 选择当前开发分支；尚未合并时可先使用 tag 自动触发。Actions 必须启用且允许工作流中使用的固定提交 Actions。checkout/setup-node/upload/download 已使用 Node 24 运行时版本，项目构建与 SEA 的 Node 版本仍固定为 22.23.3；两者不是同一个配置。GitHub 发布使用内置 `GITHUB_TOKEN`，无需个人 Token；只有 tag 的发布 job 获得 `contents: write`。Updater 签名使用下面说明的专用密钥，不等同于 Apple / Authenticode 签名。

### 桌面自动更新与签名配置

正式桌面版启动后和每 6 小时自动检查 GitHub Latest 正式版；发现新版无需确认，自动下载、校验签名、安装并重启。“关于”页面展示版本、进度和失败信息，失败可手动重试，也会在后续定时检查时重试。下载与签名校验完成后才停止 Runtime / Tunnel，安装后重启；不会自动运行 Runtime。下载失败保留当前执行，停止失败不安装，安装或重启失败显示可重试状态。网页版本不会调用桌面 updater，开发壳不会自动更新为正式包。

更新强制校验签名和签名绑定的版本，拒绝改包、错版本、错误公钥。正式环境只允许 HTTPS。Windows 按 NSIS / MSI、Linux 按 AppImage / DEB 匹配安装格式。默认 NSIS 为当前用户安装，updater 使用 `quiet` 模式，无安装向导升级；原生检测到 MSI 安装格式时采用 `passive` 无确认流程，以便系统请求所需管理员权限，避免 quiet 权限失败后应用直接退出。MSI 可能显示系统安装进度。Linux DEB 和无写权限的 macOS 安装目录可能需要系统授权，不能绕过；普通可写 macOS `.app` / Linux AppImage 可自动替换。自动重启前请及时保存正在编辑的配置。`v0.5.12` 起采用上述自动安装策略；`v0.5.11` 用户升级到 `v0.5.12` 时仍需点击一次“下载更新并重启”，之后的正式版无需确认。更早没有 updater 的版本需手动安装首个支持更新的版本，不能凭发布新 Release 获得该能力。[Tauri 官方 updater](https://v2.tauri.app/plugin/updater/)。

本机已生成长期密钥，私钥位于 `.local/updater/micromatrix.key`，权限 `600`；整个 `.local/` 被 Git 忽略，只有公钥写入 Tauri 配置。**务必离线备份，不要重新生成替换，不要提交或粘贴私钥到聊天/日志。** 当前密钥没有额外口令，安全性依赖本机文件权限、离线备份和 GitHub Secret 保护。

发布前在仓库 **Settings → Secrets and variables → Actions** 配置 `TAURI_SIGNING_PRIVATE_KEY`，值为私钥文件内容；当前无口令密钥不需要设置密码 Secret。若已安装并登录 GitHub CLI，可在项目目录执行（不打印私钥）：

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY \
  --repo HideInMatrix/micromatrix-workbench < .local/updater/micromatrix.key
```

如使用有口令的密钥，另配置 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。本地 `npm run tauri:build` 自动使用上述私钥路径，也可通过同名环境变量指定自己的密钥；新克隆需从安全备份恢复私钥或设置环境变量。`tauri:dev` 不需要私钥。

Workflow 在 verify 阶段检查 Secret 是否存在，缺少则立即失败，不浪费四平台编译时间；原生 build 生成签名包，发布前再次验证各平台校验和、签名与版本，完整成功才自动公开正式 Release。正常 tag 成为 Latest，预发布 tag 不进入正式更新通道。GitHub 签名 Secret 已配置，`v0.5.11` 的四平台构建及正式 Release 已验证；新仓库仍须单独配置。

### 构建复用与 Rust 缓存

`Desktop packages` 的 verify 只构建一次 Vite 页面并上传 `shared-web`，四个原生 job 下载同一份页面。各平台保留类型检查和 SEA 冒烟，随后通过 `build:sidecar -- --prebuilt-web` 内嵌页面；Tauri 使用 `tauri.prebuilt.conf.json` 关闭重复的前端 hook。服务 CJS、Node SEA 和 Rust 仍在各原生平台构建，不复用其他系统的可执行文件。本地默认构建命令仍会自动构建前端；预构建模式缺少有效 `index.html` 时会直接失败。

Rust 使用固定 SHA 的 `Swatinem/rust-cache` 缓存 Cargo 下载和依赖编译产物，按平台/架构、工具链和依赖配置隔离，不降低 release 优化级别。建议提交推送后，先手动选择 **master** 跑一次完整构建，预热默认分支缓存；后续 tag 可以读取它。GitHub 不允许不同 tag 互读缓存，因此仅连续推送 tag 不能保证命中上个 tag 的缓存；本流程只在 master 保存缓存。[GitHub 缓存作用域](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)、[Rust Cache 行为](https://github.com/Swatinem/rust-cache#cache-details)。

首次冷构建仍需要编译 Rust 依赖；runner 排队、下载和安装包压缩不会被编译缓存消除，不保证固定分钟数。各平台的 `rust-timings-*` Artifact 保留 Cargo HTML 耗时报告，方便定位后续瓶颈；它和 `shared-web` 不会加入 Release。复用前端仅适用于目前各平台相同的 Vite 配置，未来如引入平台特定的构建变量需重新评估。

Release 提供 **6 个安装包 + 2 个 macOS `.app.tar.gz` 更新包 + `latest.json` + `SHA256SUMS.txt`**，加上 GitHub 自动提供的两个源码压缩包。macOS 更新包用于应用内升级，不是独立服务；Windows / Linux 复用签名后的安装包。签名嵌入 `latest.json`，`.sig`、构建 JSON 和通知不重复作为公开附件。`scripts/prepare-release-assets.mjs` 使用平台/格式白名单，缺少格式、重复安装包或校验失败都拒绝发布；不直接把 Actions 的所有文件上传。

独立服务压缩包、构建 JSON、原始校验文件仍保留在 Actions 的 `micromatrix-*` Artifacts，不作为 Release 附件。**这不是私密存储策略**：公开仓库中，有权限访问 Actions 的用户仍可能下载这些文件。桌面应用内的 Node SEA sidecar 仍是运行所需组件，不会移除。

`build:sidecar` 同时生成 Node/Pi 许可证、第三方通知和已知限制；Tauri 通过 `bundle.resources` 将其放进安装后应用的 `notices/` 资源目录，不再作为公开附件重复分发。生成目录不追踪 Git。这只覆盖目前列出的通知，完整依赖许可证审计仍未完成。[Tauri 资源配置](https://v2.tauri.app/reference/config/#resources)。

macOS 使用 ad-hoc 签名、没有公证；Windows 未进行 Authenticode 签名。编译通过不是平台安装验收，当前仍是测试包。流水线依据 [Tauri 打包指南](https://v2.tauri.app/distribute/pipelines/github/)、[GitHub 手动触发要求](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)和 [Node SEA 构建流程](https://nodejs.org/download/release/latest-v22.x/docs/api/single-executable-applications.html)。

macOS 保持 Hardened Runtime，补充 V8 所需 JIT/可执行内存 entitlements。不能只测打包前的 SEA：Tauri 会重新签名 sidecar，因此原生 macOS job 在打包后另跑 `scripts/smoke-sidecar.mjs --bundled`，验证最终包内进程能启动、显示版本正确、Runtime 闲置且 MCP 端口未监听。[Apple JIT 与 Hardened Runtime](https://developer.apple.com/documentation/Apple-Silicon/porting-just-in-time-compilers-to-apple-silicon)。

开发约束见 [`docs/architecture.md`](docs/architecture.md)，第三方许可证见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。依赖版本以 `package.json`、`package-lock.json` 和 `src-tauri/Cargo.lock` 为准。
