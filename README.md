# micromatrix agent

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

桌面 UI 会先等待控制服务就绪，再加载配置；这不是启动 MCP 或 Tunnel。sidecar 无法启动或退出时，页面显示具体诊断和“重新加载配置”，不再只显示 `Load failed` 或无限等待。软件名为 `micromatrix agent`；桌面 PNG/ICO/ICNS 使用旧版提供的原图标，侧栏标识保持不变。为保留现有配置，应用 identifier 与配置目录不改名。

SEA 中 Pi 的资源目录默认固定在可执行文件所在目录，不向上扫描源码目录寻找 `package.json`；避免尚未点击启动就触发工作目录/Documents 的读取授权。显式配置的 `PI_PACKAGE_DIR` 仍保留。

`npm run dev` 只启动控制 API，不启动 Vite UI 或 MCP。Tauri 开发窗口使用：

```bash
npm run tauri:dev
```

所有 `tests/` 目录仅保留本地，Git 不再跟踪；新克隆不包含测试文件。`npm run check` 只做类型检查和 Web 构建，保留测试文件的开发机可以另跑 `npm test`。远端 CI 不再提供这些单元/集成测试的回归保障，桌面打包仍执行 SEA 冒烟检查。

## MCP 认证

本机回环地址可以无认证运行。需要通过 Tunnel 或非回环地址公开时，必须配置以下任一项，否则 Runtime 拒绝启动：

- `MICROMATRIX_OAUTH_PASSWORD`：供网页 MCP 客户端使用的 OAuth 2.0 + DCR + PKCE 流程。
- `MICROMATRIX_AUTH_TOKEN`：兼容旧客户端的静态 Bearer Token。

客户端连接地址为 `https://<public-host>/mcp`。OAuth client、authorization code 和 token 只保存在进程内存中，Runtime 重启后失效。

Runtime 启动后，浏览器访问公网域名根路径 `/` 会返回 JSON 服务信息：应用名称/版本、支持的 MCP 协议、`/mcp` 端点、认证方式和当前工具名称/数量。此信息无需认证，但不包含工作目录、配置或密钥，也不是本地管理页面；MCP 调用仍按配置认证和审批。端点使用相对路径，兼容 Cloudflare 随机域名与固定域名。

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

UI 配置默认写入 `~/.micromatrix-pi-mcp/runtime.json`。关闭“保存敏感信息”后，OAuth 密码和网络令牌不写入磁盘。密码框留空表示保留现有值；只有点击对应的清除按钮并保存才会删除已有密钥。

单文件服务上的内嵌 Web UI 使用页面自己的 origin，可使用自定义控制端口；Vite/Tauri 默认连接 `http://127.0.0.1:8233`，如需自定义应在构建前设置 `VITE_CONTROL_URL`。

## GitHub Actions 打包

- 分支 push / PR：`CI` 自动准备应用版本、运行类型检查和 Web 构建。
- 手动运行 `Desktop packages`：检查后构建 macOS arm64/x64、Windows x64、Linux x64 的实验性安装包，并执行各平台 SEA 冒烟；下载入口为该次运行的 **Artifacts**。
- 推送 `v*` tag：执行同样的打包流程；全部平台成功后，只选择 6 个桌面安装包，验证各平台 SHA-256 并合并为 `SHA256SUMS.txt`，上传完成后自动公开为 **Pre-release**。独立服务、构建 JSON 和单独通知文件不上传 Release。任意平台失败不会进入发布；上传失败保留草稿，不公开不完整的版本。实验包不标记为稳定版 Latest。

提交当前实现、脚本和 `.github` 后推送分支，再推送一个未使用的 tag，例如：

```bash
git push origin master
git tag v0.5.3
git push origin v0.5.3
```

这些命令要求修改已经提交；不要把 tag 打在旧提交上。**发布版本以 tag 为准，不再要求手动修改多处版本文件**。例如 `v0.5.2` 构建为 `0.5.2`，`v0.6.0-rc.1` 构建为 `0.6.0-rc.1`，不必与源码当前的 `0.5.0` 相等。

`git tag` 本身只创建引用，不修改文件。Actions 根据 `GITHUB_REF_TYPE=tag` 和 `GITHUB_REF_NAME`，在每个构建 job 执行 `scripts/release-version.mjs`，自动同步根 `package.json`、npm 锁文件、Tauri 配置、Cargo 配置/锁文件和应用显示版本；只修改构建工作区，不自动提交回仓库，不改内部插件/依赖版本。完整 tag、commit 和构建平台记录在 `build-*.json`。非 tag 构建使用根 `package.json` 的版本。[GitHub 提供的引用变量](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)。

只保留 `v` + SemVer 格式校验（如 `v1.2.3`、`v1.2.3-beta.1`）；任意字符串不能作为 npm/Cargo/Tauri 应用版本。安装包、服务和显示版本需要一致，但一致性由构建脚本自动生成，而非人工维护。

旧 tag 的失败运行重新执行仍使用旧提交，不会自动读取 master 上的修复。提交并推送修复后，可手动选择 master 打包，或推送指向修复提交的新测试 tag；不要为重试擅自覆盖已存在的 tag。

旧流程只保存 Release 草稿，且附件包含独立服务和审计文件。新流程自动发布精简附件，但不会重写已有公开版本；已有附件不会因修改 workflow 自动消失。已有草稿若包含白名单外附件，新流程拒绝公开，须先手动清理或使用新 tag。

手动触发需要 workflow 文件已经存在于仓库默认分支，随后可在 Run workflow 选择当前开发分支；尚未合并时可先使用 tag 自动触发。Actions 必须启用且允许工作流中使用的固定提交 Actions。checkout/setup-node/upload/download 已使用 Node 24 运行时版本，项目构建与 SEA 的 Node 版本仍固定为 22.23.3；两者不是同一个配置。默认使用内置 `GITHUB_TOKEN`，无需提供个人 Token 或生产签名密钥；只有 tag 的发布 job 获得 `contents: write`。

### 构建复用与 Rust 缓存

`Desktop packages` 的 verify 只构建一次 Vite 页面并上传 `shared-web`，四个原生 job 下载同一份页面。各平台保留类型检查和 SEA 冒烟，随后通过 `build:sidecar -- --prebuilt-web` 内嵌页面；Tauri 使用 `tauri.prebuilt.conf.json` 关闭重复的前端 hook。服务 CJS、Node SEA 和 Rust 仍在各原生平台构建，不复用其他系统的可执行文件。本地默认构建命令仍会自动构建前端；预构建模式缺少有效 `index.html` 时会直接失败。

Rust 使用固定 SHA 的 `Swatinem/rust-cache` 缓存 Cargo 下载和依赖编译产物，按平台/架构、工具链和依赖配置隔离，不降低 release 优化级别。建议提交推送后，先手动选择 **master** 跑一次完整构建，预热默认分支缓存；后续 tag 可以读取它。GitHub 不允许不同 tag 互读缓存，因此仅连续推送 tag 不能保证命中上个 tag 的缓存；本流程只在 master 保存缓存。[GitHub 缓存作用域](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)、[Rust Cache 行为](https://github.com/Swatinem/rust-cache#cache-details)。

首次冷构建仍需要编译 Rust 依赖；runner 排队、下载和安装包压缩不会被编译缓存消除，不保证固定分钟数。各平台的 `rust-timings-*` Artifact 保留 Cargo HTML 耗时报告，方便定位后续瓶颈；它和 `shared-web` 不会加入 Release。复用前端仅适用于目前各平台相同的 Vite 配置，未来如引入平台特定的构建变量需重新评估。

Release 仅有 **6 个安装包 + 1 个 `SHA256SUMS.txt`**，加上 GitHub 自动提供的两个源码压缩包，共 9 项。`scripts/prepare-release-assets.mjs` 使用平台/格式白名单，缺少格式、重复安装包或校验失败都拒绝发布；不直接把 Actions 的所有文件上传。

独立服务压缩包、构建 JSON、原始校验文件仍保留在 Actions 的 `micromatrix-*` Artifacts，不作为 Release 附件。**这不是私密存储策略**：公开仓库中，有权限访问 Actions 的用户仍可能下载这些文件。桌面应用内的 Node SEA sidecar 仍是运行所需组件，不会移除。

`build:sidecar` 同时生成 Node/Pi 许可证、第三方通知和已知限制；Tauri 通过 `bundle.resources` 将其放进安装后应用的 `notices/` 资源目录，不再作为公开附件重复分发。生成目录不追踪 Git。这只覆盖目前列出的通知，完整依赖许可证审计仍未完成。[Tauri 资源配置](https://v2.tauri.app/reference/config/#resources)。

macOS 使用 ad-hoc 签名、没有公证；Windows 未进行 Authenticode 签名。编译通过不是平台安装验收，当前仍是测试包。流水线依据 [Tauri 打包指南](https://v2.tauri.app/distribute/pipelines/github/)、[GitHub 手动触发要求](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)和 [Node SEA 构建流程](https://nodejs.org/download/release/latest-v22.x/docs/api/single-executable-applications.html)。

macOS 保持 Hardened Runtime，补充 V8 所需 JIT/可执行内存 entitlements。不能只测打包前的 SEA：Tauri 会重新签名 sidecar，因此原生 macOS job 在打包后另跑 `scripts/smoke-sidecar.mjs --bundled`，验证最终包内进程能启动、显示版本正确、Runtime 闲置且 MCP 端口未监听。[Apple JIT 与 Hardened Runtime](https://developer.apple.com/documentation/Apple-Silicon/porting-just-in-time-compilers-to-apple-silicon)。

开发约束见 [`docs/architecture.md`](docs/architecture.md)，第三方许可证见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。依赖版本以 `package.json`、`package-lock.json` 和 `src-tauri/Cargo.lock` 为准。
