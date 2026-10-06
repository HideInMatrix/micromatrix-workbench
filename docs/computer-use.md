# Computer Use MCP · ASIL 风格首版

## 论文到工程的取舍

《ASIL: Replacing Screenshot-and-Click with Structured State and Semantic Actions》的核心是：暴露软件状态，而不是从截图猜测；动作表达软件操作，而不是坐标点击；执行后用独立状态约束检查结果。优先使用文件格式、软件原生接口、脚本或已有成熟 MCP，无法取得内部状态时才用较浅的接口。论文不等于“任何封闭软件都能完整控制”。[作者项目页](https://sharryxr.github.io/ASIL/)、[参考实现](https://github.com/sharryXR/ASIL)。

本项目独立实现 TS7 MCP 服务，原生 API 经系统代理访问：macOS 是固定 Swift helper，Windows 是固定 C# UIA helper；它们只有 ABI 操作，没有模型、审批或第二套业务引擎。不引入 Python 运行时，没有复制上游 Python 执行引擎；结构受论文启发，但不是上游协议兼容实现，不能套用论文成功率或声称实现了全部 15 个应用。

```text
网页 AI（推理 / 选工具）
  → 现有 OAuth MCP / 审批入口
  → Pi MCP ExtensionFactory 注册的工具
  → Computer Use stdio MCP（无模型 / 无规划器）
  → DesktopProxy / JSON Adapter：observe → validate → execute → observe / verify
    → NativeDesktopChannel → macOS AX 或 Windows UIA（按 OS 自动选择）
```

`packages/computer-use` 拥有适配器、共享协议、状态校验、生命周期和有限追踪。应用 UI 只管理已有 MCP 配置，不维护第二套执行目录。

## 已实现范围

| 适配器 | 状态来源 | 动作 | 边界 |
| --- | --- | --- | --- |
| `desktop` | macOS Accessibility：运行应用、控件角色/标签/值/可用操作 | 激活已观察应用；设置可写值；执行控件声明的 press / show_menu / raise | 必须授予辅助功能权限；不是完整内部状态；不支持安全输入框、坐标点击、任意键鼠注入或启动未观察应用 |
| `desktop` (Windows) | UI Automation 控件树与运行窗口 | Value/RangeValue 设置；Invoke/Toggle/SelectionItem/ExpandCollapse 语义操作；激活已观察应用 | Windows 10/11 x64，.NET Framework 4.8；锁屏、UAC 安全桌面、密码控件拒绝，不自动提权 |
| `json` | Workspace 内现有 JSON 与完整内容 revision | 修改已观察叶子，保留其他数据并原子替换文件 | 非隐藏、非凭证命名的 .json，最大 256 KiB；不创建任意文件，不代表 GUI 未保存状态 |

**Linux 客户端暂不支持**：桌面代理与原生构建明确拒绝，CI 不生成 Linux 安装包或 updater 条目。不删除历史发布包。Windows 后端已实现并接入构建，使用 Microsoft Roslyn / C#5 和 .NET Framework 4.8 引用实际交叉编译通过；本轮没有 Windows 实机，不能把编译或共用代理测试当成 Windows UIA 操作验收。macOS 与 Windows 使用相同 MCP 工具/参数/审批/回读逻辑，模型不选择系统分支。

观察包含 `meta / app_state / interactive_elements / environment / navigation / data_summary`，附带 revision。控件有 ID、值、子节点及允许动作；值可能截断/脱敏。AX / UIA ID 只在当前 helper 会话内有效，不能跨重启复用；JSON 目标使用 JSON Pointer，例如 `json:/status`。

## 接入当前程序

1. 安装包含本轮改动的新构建。已发布的 v0.5.16 仍是手动预填入口，不包含本轮内置管理与授权 UI。
2. Runtime / 插件页已有 **Computer Use · 内置 Pi MCP 插件**，无需添加、填写程序路径或参数，默认关闭。显式打开开关只保存启用标志，**不启动 Runtime/Tunnel，也不弹 OS 授权**。
3. 页面检查实际原生 helper 状态。macOS 未授权时显示原因、准确 helper 路径和三步引导；用户明确点击“申请权限并打开系统设置”才发起 TCC 提示、打开固定权限页，用户亲自打开对应权限。返回应用/点击重新检测以及有限期复检只做无提示检查，不能将“已打开系统设置”当作授权成功。
4. 权限就绪后仍由用户点击 Runtime 启动；启动也会无提示检查信任状态。Windows 检查 unlocked interactive desktop，明确高权限/UAC 边界，无自动提权、无伪造 macOS 设置入口。JSON 操作不要求 Accessibility 授权，GUI 观察/动作仍被 OS 阻止。
5. 网页 AI 连接现有公网 MCP，首次启用后在 ChatGPT Home/MCP 管理页 **刷新工具**，再发起请求；工具名以实际 tools/list 为准。OS 权限与现有 open_world 逐次审批独立，不能自动跳过。

旧官方预填 MCP 自动迁移为内置开关，保留 enabled/readonly；未点击保存前只在内存归一化，不改原配置或秘密。当前安装重新派生程序/工作区参数，不执行旧包路径。用户自定义的同名第三方服务不覆盖、不偷换；需先改其 ID。旧只读项必须明确点击“启用控制动作”才升级。

危险模式会自动放行；“会话批准”按既有 open_world 权限放行该认证会话的后续操作，不是只批准一个按钮。保存、打开软件和控制面启动都不启动 Computer Use MCP；只有 Runtime 显式启动才加载内置 stdio 子进程。权限检测是独立的短生命周期 helper 检查，不连接 MCP、不读取应用内容；新安装首次加载关闭状态不做权限探测。连接测试仅发现工具并清理，不调用权限工具。停止时 Pi 关闭连接和 owned 子进程树，helper 随之关闭。

不独立监听 HTTP 端口，也不新增 Tunnel / OAuth。

### macOS 授权

先调用 `computer_permissions({"request":false})`，仅检查，不弹系统权限。若 accessibility=false：

- 用户在 **系统设置 → 隐私与安全性 → 辅助功能** 授权返回的 helper 路径，或系统标识的负责应用 micromatrix agent。
- 可明确批准 `computer_permissions({"request":true})` 请求系统提示；仅启用动作后允许，不会自动授予权限。
- 授权后必要时停止并重启 Runtime，重新观察。当前不请求屏幕录制权限。

**工具审批与 OS 授权是不同的两层权限**，不能靠批准工具绕过 TCC。未授权时 observe 返回真实 ACCESSIBILITY_PERMISSION_REQUIRED，不把空状态当成功。ad-hoc 开发包更新后可能需要再次确认系统信任，未承诺跨版本 TCC 授权永久保留。

### Windows 权限

computer_permissions 返回 interactive_desktop、elevated 和原生 helper 路径，没有 macOS 的 TCC 弹框。request=true 也不会提权、改 UIAccess 或操作 UAC；用户必须已解锁交互桌面。普通进程通常不能控制高权限/受保护目标，UIA provider 也可能只读或缺少模式；原样报告拒绝，不降级键鼠注入。Windows 定位使用同一 pid:PID，控件 ID 为 uia:运行时ID。范围值会按原生最小/最大值检查，字符串值回读按字符串比较。依据 [Microsoft UIA 模式](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview) 和 [TreeWalker](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/navigate-among-ui-automation-elements-with-treewalker)。

## 工具合同

| 工具 | 用途 |
| --- | --- |
| computer_capabilities | 适配器、平台边界、动作启用状态 |
| computer_targets | 运行 GUI 应用 PID 和顶层可选 JSON；不启动应用 |
| computer_permissions | 检查系统访问；仅 macOS 显式请求辅助功能权限 |
| computer_observe | `{adapter:"desktop"或"json", target:"pid:123"或"input.json"}` |
| computer_validate | 无副作用检查 schema、观察目标、revision；不是批准或执行 |
| computer_act | 单次语义动作，回读并报告独立验证结果 |
| computer_trace | 最近 100 个元数据结果：类型、耗时、状态；不记录应用内容或推理链 |

动作须携带观察返回的真实 UUID、控件 ID 和允许动作：

```json
{
  "observation_id": "替换为真实观察返回的 UUID",
  "action_type": "modify_file",
  "target": "json:/status",
  "params": {"value": "passed"},
  "expect_observation": {"target": "json:/status", "value": "passed"}
}
```

- navigate：目标 app:PID，params={}，仅激活已观察运行应用。
- set_value：目标可写 ax:N 或 uia:ID，params={"value":"文本"}，拒绝安全字段。
- invoke_function：目标 ax:N 或 uia:ID，params={"operation":"press"}；须在该控件 metadata.operations 内。
- modify_file：现有可编辑 json:/路径，params={"value":...}；不接受 eval、脚本或任意命令参数。

观察有效 **30 秒**，最多 32 项；再次观察同一目标使旧 ID 失效。执行前重新检查状态，尝试动作即消耗 ID，包括结果未知的失败。审批等到过期时重新观察，不能关闭校验。

execution=executed 只表示动作已发出，**不等于任务成功**。verification.status 为 passed / failed / not_requested，只按提供的独立目标值严格比较；没提供约束就不能宣称验证通过。应用异步更新时重新观察最终状态，不重复提交。

超时、控件消失、进程退出、原生错误均返回 MCP isError=true 与错误码，结果可能未知。**不要自动重试发送/删除/提交**，先重新观察。没有自动寻找 Shell/坐标点击的替代路径。

## 运行和打包

macOS 原生编译需要 Xcode Command Line Tools / Swift，明确以 macOS 11.0 为部署目标，不继承构建机器的系统版本；平台配置同步声明最低 11.0。构建时编译和签名，不在打开应用时下载/编译。最低版本声明不是 macOS 11 实机验收。

```bash
npm run typecheck
npm run prepare:computer-use  # 编译当前系统 helper；Linux 拒绝
npm run dev:computer-use     # stdio MCP，默认只读，需 MCP Client 连接
npm run dev:computer-use -- --allow-actions --workspace /absolute/path/to/workspace
npm run check:sidecar        # SEA、Pi 接入与临时 JSON 的真实冒烟
```

Windows 编译使用系统 .NET Framework 4.8 的 csc/WPF 引用，产物是固定 .exe，不在使用时运行 PowerShell 或编译模型代码。桌面构建自动准备当前 OS helper，经 tauri.macos.conf.json / tauri.windows.conf.json 加入应用；macOS 不引用 Windows .exe，Windows 不引用 Swift 二进制。scripts/smoke-computer-use.mjs 用 SDK 连接真实 SEA，保留随机 marker、修改 JSON、验证回读、拒绝旧 ID；macOS 只检查权限，不请求授权或操控用户桌面。Windows SEA 冒烟同样握手并检查原生桌面状态，在非交互 runner 上验证拒绝路径，不伪造 GUI 成功。既有 macOS smoke-sidecar --bundled 验证最终包内 helper 定位/执行与 Pi 注册。

本地回归包括只读拒绝、审批拒绝不写入、过期/外部修改/重复执行、非法参数/越界/敏感文件、Pi 注册与清理、Vue 表单保存不启动。tests/ 按项目要求继续 Git 忽略；随源码保留的 SEA 冒烟继续在 CI 执行。

## 验收边界与后续

授权交互参考 [OpenAI Work with Apps](https://help.openai.com/en/articles/10119604-work-with-apps-on-macos) 的启用/检查/引导方式和 [Apple 辅助功能授权说明](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac)，不是复刻其闭源实现或宣称支持其全部应用。

- 本机辅助功能权限未授予。已验证原生权限检查、真实应用发现和拒绝路径；**真实桌面修改/按钮操作尚未验收**。用户授权后应在无敏感数据的测试应用检查输入和最终状态。
- UI 文本/文档是不可信数据而非指令。敏感字段/命名值脱敏不是完整 DLP，普通标签和文本仍可能包含私密数据；只观察授权应用，公网保持认证与审批。
- 路径校验、revision 和原子写入不是 OS 沙箱，不能完全消除本机恶意进程 TOCTOU race。
- Accessibility 是结构化 GUI 回退；浏览器 DOM、Office 文档、Blender 等应分别增加原生/文件/API 适配器，不靠“万能 eval”。成熟第三方 MCP 可直接通过 Pi 复用。
- 自定义适配器当前由产品源码实现并打包，不自动执行 Workspace 中未经审查的 TS 插件。
