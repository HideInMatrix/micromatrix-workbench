# Tool 两类执行模型

## 1. 目的

Workbench 中的 Tool 不再统一理解为“一个可执行文件”。从执行边界上明确分为两类：

```text
Tool
├─ Runtime Tool
│  └─ CLI / executable / Runtime Safe Sandbox
│
└─ Host Capability
   └─ Desktop Host / GUI / system service / session resource
```

这个分类是安全边界，不是 UI 标签。新增能力前必须先判断它属于哪一类，不能因为现有 `exec_process` 可以启动程序，就把桌面应用强行塞入 Runtime Tool。

## 2. Runtime Tool

适用于生命周期近似“一次命令、一个进程、退出”的开发工具，例如：

- git
- node / pnpm / npm
- python
- go
- cargo
- ffmpeg
- terraform

执行链路：

```text
AI 请求 program
  -> Workspace-aware Host Tool Resolution
  -> 用户确认 executable/read_roots/fingerprint
  -> Profile.toolchains 持久化
  -> Runtime Safe/Trusted Sandbox 执行
```

Runtime Tool 的授权对象是 executable 身份和最小只读根。Host 只负责回答“当前用户、当前 Workspace 会执行哪个入口”，不维护 Homebrew/nvm/pyenv 等安装路径候选表。

## 3. Host Capability

适用于依赖桌面宿主、系统服务、多进程或长期 Session 的能力，例如：

- Browser / CDP
- Finder / file picker
- screen capture
- microphone / camera
- Keychain
- desktop application automation

Host Capability 不进入 Runtime `exec_process`，也不使用 `privileged_executable` 代替自己的权限。

执行链路：

```text
AI 调用 Host Capability Tool
  -> Runtime 检查专属 operation permission
  -> Desktop Permission Broker 用户确认
  -> Runtime 通过私有签名 Host Capability IPC 发起 bounded action
  -> Workbench Desktop Host 执行/维护 Session
  -> Runtime 只收到 session_id + bounded structured result
```

Runtime 不获得 GUI 应用 Bundle 的文件读取权限，不把 `/Applications`、Framework、系统服务加入 Runtime Sandbox，也不直接持有 Host GUI 进程。

## 4. ToolDefinition 执行类别

`ToolDefinition.execution_kind` 只有两个值：

```text
runtime
host_capability
```

默认值是 `runtime`，保证现有 Tool 行为兼容。Host Capability 必须显式声明 `host_capability`。

`server_info.tool_execution_kinds` 对 AI 暴露该分类，避免 AI 把 Browser 等 Host Capability 再退化为 `exec_process` 尝试。

## 5. Host Capability IPC

Host Capability 与普通权限请求共用 Desktop Broker 的私有目录和 HMAC secret，但使用独立 payload kind：

```text
kind = host_capability
```

请求绑定：

- `server_id`
- `capability`
- `action`
- `session_id`
- bounded `parameters`
- TTL
- HMAC signature

响应必须绑定相同字段并重新签名。Host Capability 请求本身不是授权；授权必须在 Runtime 调用前通过独立 operation permission 完成。

服务停止、删除或 Broker cleanup 时，Desktop Host 必须按 `server_id` 回收所有 Session。

## 6. Browser 作为第一个 Host Capability

Browser 的专属权限是：

```text
browser_control
```

Runtime 内部保留细粒度操作：

```text
browser_open
browser_navigate
browser_snapshot
browser_click
browser_fill
browser_press
browser_screenshot
browser_status
browser_close
```

为了控制 MCP 客户端 Tool surface，这些细粒度 Tool 不直接对 MCP 暴露。对外只有一个 domain facade：

```text
browser_manage(action=open|navigate|snapshot|click|fill|press|screenshot|status|close)
```

因此 Host Capability 的增加只新增一个公开 MCP Tool，不把每个 Session action 都扩成顶层 Tool。

Browser Session 特性：

- Desktop Host 启动浏览器，不经过 Runtime Seatbelt。
- 每个 Session 使用独立临时 `user-data-dir`。
- 不复用用户日常 Chrome/Edge/Brave Profile、Cookie、扩展和登录状态。
- 仅监听 `127.0.0.1` CDP。
- Session 关闭后删除临时 Profile。
- Runtime 不直接连接 CDP；CDP 控制也由 Desktop Host 执行。
- `browser_close` 不要求再次授权，保证资源始终可回收。

## 7. Browser Host Resolution

禁止维护：

```text
/Applications/Google Chrome.app
C:\Program Files\Google\Chrome\...
/usr/bin/google-chrome
```

Browser Provider 通过当前用户操作系统注册信息查询 HTTPS Handler；默认 Chromium Handler 优先，否则从当前用户已注册 Handler 中选择可用 Chromium/CDP Provider：

- macOS：LaunchServices
- Windows：URL Association
- Linux：XDG default-web-browser / Desktop Entry

解析出的应用身份属于 Host 内部信息。首版 Browser Provider 是 Chromium/CDP Provider；如果系统没有注册可用 Chromium family，会在启动前明确返回 unsupported，不用 Chromium 参数误启动 Safari/Firefox，也不扫描固定安装目录。

## 8. 权限边界

两类模型的权限必须保持独立：

```text
Runtime Tool
  toolchain_registration
  network
  git_metadata_write
  sandbox_env_override
  ...

Host Capability
  browser_control
  future: screen_capture
  future: microphone_access
  ...
```

`privileged_executable` 继续只服务于外部 stdio MCP，不扩展为“任意宿主程序启动权限”。

`sandbox_env_override` 只控制 Runtime 子进程环境变量，也不能用于 Host Capability。

## 9. Browser MVP 验收

状态：**已验收 / 已封板（2026-09-09）**

真实 Desktop Client Browser Gate 已通过。验收环境为 `safe + full isolation`，实际由 Desktop Host 通过 macOS LaunchServices 解析到 `com.google.Chrome`，使用 `desktop_chromium_cdp` Provider 创建独立临时 Profile，并完成同一 Session 内的 CDP 页面控制。

真实 Gate 结果：

- `open`：成功创建隔离 Browser Session；`application_source=launch_services`、`application_id=com.google.Chrome`、`isolated_profile=true`。
- `navigate`：成功进入 `https://example.com/`。
- `snapshot`：成功读取 `Example Domain` 页面文本并识别可交互元素 `Learn more`。
- `status`：Session 保持 `alive=true`，Provider 为 `desktop_chromium_cdp`。
- `close`：返回 `closed=true`，Session 正常回收。
- 整条链路未使用 Runtime `exec_process`、`privileged_executable`、`sandbox_env_override` 或固定 Chrome 安装路径。

1. `server_info` 能区分 Runtime Tool 与 Host Capability。
2. 首次 `browser_open` 弹 `browser_control`，而不是 `privileged_executable`。
3. 用户批准后 Desktop Host 启动独立 Chromium/CDP Session。
4. 浏览器 Profile 不位于用户正常 Profile 目录。
5. Runtime 不需要 `/Applications` readable root。
6. `browser_snapshot/click/fill/press` 能在同一 Session 连续操作。
7. screenshot 只能写入当前 Workspace。
8. `browser_close` 删除临时 Profile。
9. MCP Server stop/delete 后 Browser Session 自动回收。
10. 非 Chromium 默认浏览器必须安全失败，不能退回普通 `exec_process`。

## 10. Host Identity Execution

宿主身份不是第三类 Tool，也不建立 `git/npm/docker/ssh` Auth Adapter Registry。它是 Runtime Tool 的一种显式执行模式：当某一条结构化进程调用确实需要当前桌面用户的登录态、配置或 Credential Store 时，调用方设置 `use_host_identity=true`，并对这一条完全相同的 invocation 请求 `host_identity_use`。

```text
exec_process(program, args, use_host_identity=true)
  -> Runtime 正常解析真实 executable
  -> Runtime 正常执行命令/环境/Workspace 安全校验
  -> 请求 host_identity_use（仅当前 exact invocation）
  -> signed Host Identity Execution IPC
  -> Desktop Host 重新校验 executable registration / fingerprint
  -> Desktop Host 在真实用户身份上下文中启动同一 executable + argv
  -> Host 侧继续施加 OS Sandbox：Workspace 可写、宿主 Home/真实 PATH/Agent Socket 只读
  -> stdout/stderr/status 通过 bounded IPC 返回
  -> 长任务继续使用同一个 process_control API
  -> Server stop/delete 时 Host 进程自动回收
```

核心原则：

- Runtime 不解析 `push/publish/login` 等工具语义，也不判断程序“是否需要认证”。是否请求宿主身份由当前调用显式声明。
- 不存在 `auth/adapters/git.py`、`npm.py`、`docker.py` 等随 Tool 数量增长的认证适配层。
- `host_identity_use` 绑定当前 principal、完整 Tool arguments、已注册 executable、argv、cwd 和 Workspace；Desktop UI 只允许拒绝或“仅允许本次”。
- Host Identity 只对结构化 `exec_process` 开放；`exec_command` 的任意 Shell 字符串不能切换到宿主身份执行。
- Desktop Host 不把 HOME、PATH、Token、Password、Credential Helper 输出或其他宿主环境作为 Tool Result 返回给 AI。
- Host 使用当前真实宿主环境，而不是固定 Homebrew/nvm/docker/git 安装目录表；实际 PATH 根和 Agent/Socket 路径只作为 Host 内部只读执行范围。
- Host 在执行前重新校验 Runtime 已确认的 executable registration 和文件 fingerprint，路径或文件变化后拒绝启动。
- Host Identity Execution 仍然需要完整 OS 文件/网络隔离；Sandbox 无法建立时拒绝降级到无约束 Host process。
- Host 侧写权限仍限制在当前 Workspace 和自己的临时 Runtime；宿主 Home 与工具安装目录保持只读。`.git` 是否可写继续服从 `git_metadata_write`，而不是因为使用宿主身份自动放开。
- `process_control` 对普通 Runtime command 和 Host Identity command 使用同一公开契约；`command_id` 只决定内部路由，不增加新的 MCP Tool。

因此 Tool Catalog 从几十种扩展到数百种时，Host Identity 核心不需要增加对应认证代码。只要该 CLI 在真实桌面用户环境中本来就能通过 HOME、系统 Credential Store、Agent Socket 或其现有 helper 完成认证，经过本次 `host_identity_use` 授权后即可使用同一执行模型。

