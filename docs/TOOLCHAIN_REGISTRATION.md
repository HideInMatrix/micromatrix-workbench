# 用户工具注册与 Host Resolution

## 核心原则

Workbench 不维护“某种工具通常安装在哪里”的知识，也不通过扫描 Home、版本管理器目录或包管理器目录来猜工具路径。

Safe / Trusted 模式下，首次使用一个尚未注册的 CLI 程序时，统一走以下链路：

```text
Runtime 请求 program=git/node/python3/ffmpeg/...
  -> Workbench Host 在真实用户环境中执行受控路径解析命令
  -> Host 只返回绝对 executable、必要只读范围和解析元数据
  -> Runtime 不接收 PATH、HOME、凭据、Shell stdout/stderr 等主机环境内容
  -> Workbench 桌面弹出注册授权
  -> 用户选择“允许并记住此 Profile”
  -> 桌面端校验提案指纹未变化
  -> 保存 executable / read_roots / 文件指纹
  -> 保存 Profile.toolchains
  -> 当前 Runtime 热加载新的只读范围并继续原命令
```

维护时禁止通过新增以下内容来“支持更多工具”：

```text
/opt/homebrew/...
/usr/local/...
~/.nvm/...
~/.pyenv/...
~/.asdf/...
~/.volta/...
某浏览器固定安装目录
其他用户安装目录候选表
```

这些路径只能作为 Host 真实解析结果出现，不能成为 Runtime 的发现规则。

## Host 路径解析

POSIX 桌面端使用当前用户的登录 Shell 执行受控 `command -v` 路径解析。Shell 初始化发生在 Workbench Host，而不是 Runtime 沙箱；Host 不把完整 Shell 环境或输出返回给 AI。

macOS 对 Apple Developer Tools 额外处理系统 shim：当登录环境解析到的工具与系统默认命令一致，并且 `xcrun --find <program>` 给出不同的真实 Developer Tool executable 时，注册真实 executable。这里仍然通过系统命令查询，不枚举 Xcode 或 Command Line Tools 安装路径。

Windows 使用系统命令解析可执行文件路径。无论平台如何，最终进入授权界面的必须是已验证的绝对路径。

Host Resolution 请求通过 Desktop Permission Broker 的私有、签名 IPC 通道完成，但它本身不是权限批准：路径解析完成后仍必须单独显示注册授权，用户确认后才能扩大 Runtime 的只读/执行范围。

## Safe PATH 与用户工具

Safe Runtime 的默认 PATH 只保留操作系统基础目录。Homebrew、`/usr/local`、版本管理器和其他用户安装位置不再预先加入 Safe PATH。

因此用户工具的正常首次使用过程是：

```text
真实用户 Shell 能找到工具
  -> Host Resolution 返回真实路径
  -> 用户批准该路径及只读依赖
  -> Runtime 注册并使用
```

如果 Host 返回的路径与 Runtime 已经允许使用的系统基础 executable 完全相同，则不产生没有意义的重复授权。

## 注册模型

程序名不再限制为 Node/Python 的固定枚举。任何满足安全名称规则的 CLI program 都可以注册，例如：

```text
git
node
pnpm
python3
go
cargo
ffmpeg
terraform
```

注册记录包含：

- `program`
- `executable`
- `read_roots`
- executable SHA-256 指纹

`version`、`runtime_target` 和 `runtime_fingerprint` 仅作为旧记录或诊断信息兼容，不再是注册成立的必要条件，也不会为了填充这些字段在注册阶段执行工具。

Host 在弹出授权前还会计算 `proposal_fingerprint`。用户点击允许时桌面端必须重新计算并比较；路径或目标文件在等待确认期间发生变化时，拒绝注册并要求重新解析。

程序文件、路径或符号链接目标发生变化后，已有注册被视为 stale，不能自动接受新的二进制。对于版本管理器 shim，授权对象就是 Host 实际解析出的入口及用户确认的只读范围；Workbench 不再执行工具去猜测它下一步会选择哪个解释器。

## 手动注册

服务设置仍保留手动入口，用于用户明确知道 executable 路径或自动 Host Resolution 无法满足特殊环境的情况。

1. 输入任意合法程序名，不再使用 Node/Python 固定下拉列表。
2. 输入绝对 executable 路径。
3. 必要时补充额外只读目录。
4. 检查自动推导的 executable、符号链接目标及只读范围。
5. 确认后计算文件指纹并保存服务；注册阶段不执行该工具。

禁止把整个 Home、Home 上级目录或凭据目录注册为只读工具根。

## 环境隔离

Runtime 不继承主机凭据、`NODE_OPTIONS`、`PYTHONPATH` 等敏感执行环境。工具缓存写入 Runtime 专用目录。

部分版本管理器需要真实 `HOME` 字符串才能定位其安装结构，因此“环境中存在真实 HOME 路径”不等于“沙箱允许读取整个 Home”。OS 沙箱仍只开放已批准的工具根。

Git 在 Safe / Trusted 模式下额外设置：

```text
GIT_CONFIG_GLOBAL=/dev/null
GIT_TERMINAL_PROMPT=0
```

这样真实 Git 不会读取 `~/.gitconfig` 或弹出凭据交互。AI 如需覆盖这些沙箱控制变量，仍必须获得 `sandbox_env_override` 授权。Safe 模式不会因注册本机 Git 而自动获得用户 GitHub 凭据。

## 注册阶段禁止工具执行

注册流程不得为了兼容某个系统或某个工具，增加类似“允许某个缓存文件写入”的平台特例。Workbench 不需要知道 Git、Node、Python、编译器或浏览器在不同系统上会创建哪些缓存。

路径解析可以使用宿主系统提供的命令/API，因为它的目标只是回答“当前用户执行这个 program 时，实际入口是什么”。解析完成后，注册阶段只读取并冻结这个入口及用户确认的只读范围；真正的程序执行发生在原始任务继续时，并受正常 Safe / Trusted Sandbox 约束。

## 审批与失败行为

- Host 路径解析不是授权，解析成功后仍必须确认注册。
- “本次服务会话全部允许”不能代替持久化工具注册。
- 用户拒绝某个工具注册后，本次服务会话不重复弹出同一工具。
- Host 未找到工具、IPC 不可用、解析超时、指纹变化或持久化失败时，原命令不执行。
- 无 Desktop Host Resolution 通道时，不扫描 Home，也不读取登录 Shell；仅可继续使用当前已经安全可访问/已注册的程序。
- shell 中动态计算出的程序名无法可靠静态识别时，应改用明确的 `exec_process(program=...)`。

## `discover_toolchains`

`discover_toolchains` 仍提供 Node / Python / Go 的高层状态视图，但缺失程序和普通命令执行使用同一套 Host Resolution + 注册流程。

返回诊断会明确报告：

```text
host_resolution = desktop_command
host_user_environment_queried = true/false
host_environment_exposed_to_ai = false
shell_startup_files_evaluated = true/false
```

这用于区分“Runtime 自己扫描用户环境”和“Desktop Host 在用户侧解析后只返回安全结果”。

## 平台与安全边界

- macOS：Seatbelt，Safe / Trusted 要求完整文件系统与网络隔离。
- Linux：要求完整可用的 OS sandbox backend；没有完整隔离时不得把应用层规则宣传为安全沙箱。
- Windows：只有完整文件系统/网络隔离 backend 可用时才能提供与 Safe / Trusted 相同的工具注册保证。
- Dangerous：任务执行不受 Safe 沙箱约束；注册仍只冻结路径/只读范围/指纹，不额外执行工具。

指纹是安装变化检测，不是软件供应链签名认证。真正的安全边界仍是 OS 沙箱、最小只读范围、桌面用户确认和不向 Runtime 暴露主机环境。
