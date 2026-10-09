# micromatrix agent

## 用途

让网页 AI 通过 MCP 操作你的电脑：**网页 AI 负责思考，Pi Agent 负责本地执行。** 本软件不运行本地模型。

- **文件与命令**：读写工作目录内的文件，按权限策略执行 Shell 命令。
- **电脑控制**：结合桌面截图、结构化界面信息和 ASIL 语义动作操作应用。
- **能力扩展**：添加 MCP 服务和 Skills，接入 Pi 插件体系。
- **公网连接**：通过 Cloudflare Tunnel 等网络方案连接网页 MCP 客户端，并提供 OAuth 认证和工具审批。

打开软件只加载配置；点击「启动」后才运行 MCP 和隧道。Computer Use 需主动开启并授予对应系统权限，不保证读取所有应用的完整内部状态。

## 安装

前往 [GitHub Releases](https://github.com/HideInMatrix/micromatrix-workbench/releases/latest)，下载适合自己电脑的**安装包**：

| 平台 | 下载与安装 |
| --- | --- |
| macOS · Apple Silicon（M 系列） | 下载 `aarch64.dmg`，打开后将应用拖入「应用程序」 |
| macOS · Intel | 下载 `x64.dmg`，打开后将应用拖入「应用程序」 |
| Windows · x64 | 下载 `*-setup.exe` 或 `.msi`，运行安装程序 |

无需另装 Node.js、Rust 或 Python；Cloudflare 客户端已内置。Linux 桌面版暂不支持，macOS 整屏 Computer Use 需要 macOS 14 或更高版本。

首次使用：

1. 打开应用，配置工作目录、OAuth 密码和网络方案，保存后点击「启动」。
2. 将显示的 MCP 地址添加到支持 CIMD OAuth 的网页 MCP 客户端，完成授权。
3. 需要控制电脑时，在插件页开启 Computer Use；macOS 按引导授权辅助功能，截图另需屏幕录制权限。

macOS 安装包使用长期自签名证书，未经过 Apple 公证；Windows 安装包未进行 Authenticode 签名。若系统阻止打开，请先确认下载来源，再按系统提示允许运行。

应用会自动检查更新，确认安装在「关于」页面操作。`.app.tar.gz`、`latest.json` 和校验文件用于更新或校验，不是首次安装入口。

## 开源鸣谢

- [Pi Agent](https://github.com/earendil-works/pi)：本地工具执行与扩展体系。
- [ASIL](https://github.com/sharryXR/ASIL)：结构化状态、语义动作与声明式适配设计；部分 `softwaregen` 模块移植为 TypeScript。
- [Model Context Protocol SDK](https://github.com/modelcontextprotocol/typescript-sdk)：MCP 服务及客户端通信。
- [Tauri](https://github.com/tauri-apps/tauri)：桌面封装、原生能力和应用更新。
- [Vue](https://github.com/vuejs/core)、[Vite](https://github.com/vitejs/vite)：界面与前端构建。
- [cloudflared](https://github.com/cloudflare/cloudflared)：Cloudflare Tunnel 公网连接。
- [Playwright](https://github.com/microsoft/playwright)：可选浏览器交互。
- [QuickJS Emscripten](https://github.com/justjake/quickjs-emscripten)：受限 JavaScript 批量执行。
- [Node.js](https://github.com/nodejs/node)、[Rust](https://github.com/rust-lang/rust)：服务运行与桌面原生实现。

更多第三方来源、许可和已知审查边界见 [第三方声明](THIRD_PARTY_NOTICES.md)；技术细节见 [架构](docs/architecture.md)和 [Computer Use](docs/computer-use.md)。
