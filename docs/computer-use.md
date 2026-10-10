# Computer Use MCP · JavaScript 批量执行与混合交互

## 论文到工程的取舍

《ASIL: Replacing Screenshot-and-Click with Structured State and Semantic Actions》的核心是：暴露软件状态，而不是从截图猜测；动作表达软件操作，而不是坐标点击；执行后用独立状态约束检查结果。优先使用文件格式、软件原生接口、脚本或已有成熟 MCP，无法取得内部状态时才用较浅的接口。论文不等于“任何封闭软件都能完整控制”。[作者项目页](https://sharryxr.github.io/ASIL/)、[参考实现](https://github.com/sharryXR/ASIL)。

本项目使用 TS7 MCP 服务，当前原生 API 经系统代理访问：macOS 是经 LaunchServices 启动的独立 Swift 应用，Windows 是固定 C# UIA helper；它们只有 ABI 操作，没有模型、审批或第二套业务引擎。不引入产品级 Python 运行时。已按固定版本官方源码移植 softwaregen 声明式核心，并建立显式协议映射；真实软件适配器仍需继续移植，不能套用论文成功率或声称实现了全部 15 个应用。

```text
网页 AI（推理 / 选工具）
  → 现有 OAuth MCP / 审批入口
  → Pi MCP ExtensionFactory 注册的工具
  → Computer Use stdio MCP（无模型 / 无规划器）
  → ProviderRegistry：能力发现 → observe → inspect → validate → execute → observe / verify
    → computer_run：受限 QuickJS JavaScript，批量调用上述合同
    → RemoteDesktopAdapter → 选定显示器画面 + 可见窗口布局 + 前台 AX/UIA
    → NativeDesktopChannel → macOS ScreenCaptureKit / AX，Windows GDI / UIA（按 OS 自动选择）
    → VisualDesktopAdapter → 可选前台窗口截图，macOS 可附 OCR
    → 可选 BrowserAdapter → DOM / ARIA / 截图 + Playwright
    → DeclarativeAdapter → JSON 文件 / 固定原生命令 / 已批准服务 API
```

`@ouvren/computer-use@0.1.1` npm 依赖拥有适配器、共享协议、状态校验、生命周期和有限追踪；workbench 不再保留本地 Computer Use 源码 workspace。应用 UI 只管理 Pi 插件配置，不维护第二套执行目录。

核心按能力而不是软件名称分支。默认 Provider 是 remote-desktop、desktop、desktop-visual 和 json；browser 必须由本地用户显式配置，ASIL 声明式软件包是可选增强，不是控制通用 GUI 的前置条件。配置后加载经过审计与哈希批准的声明式软件适配包，不扫描 Workspace、不执行生成代码或自动安装软件。

## 默认用法：模型选择通道，用 JavaScript 批量执行

一个执行器，无第二个规划模型。网页模型根据任务选择来源，再提交 `computer_run({code, timeout_ms})`：

| 通道 | 适用任务 | 实际来源与限制 |
| --- | --- | --- |
| `remote-desktop` | 桌面全局布局、跨窗口视觉判断与操作 | 选定显示器整屏 JPEG + 最多 100 个窗口布局 + 前台应用 AX/UIA；不启动 VM/VNC/RDP 或视频轮询，不是所有应用内部状态 |
| `desktop` | 原生按钮、文本框、窗口 | AX / UIA 的真实语义，未暴露的控件不能凭空补齐 |
| `desktop-visual` | 自绘界面、画布、AX 信息不足 | 前台目标窗口 JPEG + AX/UIA；macOS 14+ 可附本地 Vision OCR，Windows 本轮没有 OCR。像素/OCR 推断不等于软件内部状态 |
| `browser` | 网页表单和导航 | Playwright 读取 DOM / ARIA 并执行动作；`page:N/visual` 额外返回截图。仅配置过的浏览器与 origins |
| `json` / 批准的 ASIL 包 | 文件、原生命令、服务 API | 保留已有结构化读写与独立回读，不以键鼠操作代替已有成熟接口 |

先发现目标；下面代码中的 `page:1` 必须替换为 `browser.tabs()` 实际返回的目标：

```js
// computer_run.code；这是受限的 Playwright 风格 API，不是 Node 或完整 Playwright Page。
const page = browser.page("page:1");
await page.getByRole("textbox", {name: "Name"}).fill("example");
await page.getByRole("button", {name: "Apply"}).click();
return await page.observe();
```

`getByRole / getByText / locator` 每次执行前重新观察、必须唯一匹配。`locator` 只支持简单 tag 或 `#id`，`selectOption(value)` 选择观察到的 select，`press` 使用有限键名，`goto` 只接受批准 origin 的 HTTP(S) URL；不暴露任意 `evaluate`、浏览器安装或用户 profile 访问。也可直接批量调用既有合同：

```js
const s = await computer.observe({adapter: "json", target: "input.json"});
await computer.act({
  observation_id: s.meta.observation_id, action_type: "modify_file",
  target: "json:/status", params: {value: "passed"},
  expect_observation: {target: "json:/status", value: "passed"}
});
return await computer.observe({adapter: "json", target: "input.json"});
```

单窗口视觉任务可提交 `computer.observe({adapter:"desktop-visual", target:"pid:真实PID"})`，整屏任务使用下节的 `remote-desktop`。返回的截图由网页模型判断；下一批传入新的观察 ID 和 `visual:surface` 的 `invoke_function`，参数从能力发现选取 `click / scroll / type_text / key`。坐标使用返回 JPEG 的像素空间，native 层换算到窗口屏幕坐标；OCR 对象的 click 使用文本框中心。原生控件仍优先执行其 AX/UIA 语义，不因失败自动退到坐标点击。截图是 MCP image content，不是塞进 JSON 的 base64；批量保留最后三张，`image_observations` 与 image content 顺序对应。JS 没有第二个模型，不能在执行器内部理解截图后自行规划。

整段代码经过现有 Pi `open_world` 审批，只读模式拒绝批量执行。QuickJS/WASM 限制：32 MiB 内存、512 KiB 栈、每段同步执行最多约 1 秒、最多 32 次 host 调用、代码 16 KiB、返回值 64 KiB；默认 30 秒、最高 60 秒。`process / require / fetch / timers / filesystem / shell` 不存在，唯一 host crossing 是有界 JSON。调用串行调度，用户应 `await`；未 await 的已请求调用也会在成功返回前排空。第一处 host 失败、取消或超限停止后续派发，报告已完成/失败步骤；已执行动作不回滚、不自动重试，先观察再判断。捕获/浏览器原生调用有自己的短超时，取消不保证撤回已经发出的系统动作。这是受限嵌入式执行器，不是整机 OS 沙箱。

### 远程桌面 + ASIL 闭环

本机 helper 承担远程桌面的采集/输入端，既有经过认证的 MCP 承担按需帧与动作传输。不新增监听端口或第二个 Agent，不启动 VM、RDP/VNC 服务或持续录像。插件和 Runtime 的手动启动方式不变；`computer_capabilities` 不启动 native helper，`computer_targets` 的屏幕枚举不捕获图像。

1. 调用 `computer_targets({adapter:"remote-desktop"})`，从实际返回中选择显示器。最多列出 16 个；不假定 ID、分辨率、主屏位置或所有屏幕都已捕获。
2. 调用 `computer_observe({adapter:"remote-desktop",target:"display:实际ID"})`，获得同一目标的 JPEG image content、`environment.remote_desktop` 窗口布局/显示器拓扑以及前台应用的 AX/UIA 树。其他应用不逐个抓取内部状态；采集前后比较布局/焦点，但并非原子快照。
3. 网页模型结合像素与事实性结构判断。有原生控件就提交该控件的语义动作，否则显式操作 `remote:surface`。
4. 执行前 helper 重新检查画面 revision、显示器布局、前台与安全输入状态；点击位置通过 native hit-test 归属到布局中的可见进程，不能凭空指定 PID。可跨窗口点击，不自动激活其他应用；文本/键盘只发往已观察前台且位于该显示器的窗口。
5. Runtime 执行一次独立后置采集，返回新图片与状态。旧 token 消耗，失败不重试；模型判断结果后再提交下一批。动画、时钟或图像变化可能导致 `STALE_OBSERVATION`，不能承诺每次图像判断都能直接执行。

下面是第一批 `computer_run.code` 的形状，显示器 ID 必须使用第 1 步的真实返回；图片由批量执行器自动附带，不在 JavaScript 中理解图片或返回 base64：

```js
const s = await computer.observe({adapter:"remote-desktop", target:"display:实际ID"});
return {meta:s.meta, frame:s.environment.frame, layout:s.environment.remote_desktop};
```

模型看图后，另一批代码使用上次真实返回的观察 ID 和图像坐标（不要照抄占位值）：

```js
const r = await computer.act({
  observation_id:"替换为上次观察ID", action_type:"invoke_function",
  target:"remote:surface", params:{operation:"click", x:实际图像横坐标, y:实际图像纵坐标}
});
return {execution:r.execution, verification:r.verification, meta:r.observation.meta};
```

`frame.bounds` 是显示器在全局屏幕空间的位置/尺寸，支持负原点；`frame.width/height` 是压缩图像像素尺寸。点击坐标只使用图像像素，helper 负责缩放与全局转换。窗口与原生控件 bounds 的单位由 `layout_coordinate_space` 标明：macOS screen points，Windows DPI-aware screen pixels。

整屏采集会包含其他可见窗口与系统 UI 的私密信息。只对已暴露的前台安全控件执行拒绝，不声称完整 DLP。macOS 14+ 使用 ScreenCaptureKit，需同一 helper 的辅助功能和屏幕录制权限；Windows 使用 GDI 显示器复制，捕获分配上限 16,777,216 源像素，受保护或硬件 overlay 内容可能缺失。输出仍限制到最长边 1280px / 384 KiB，必要时选择单窗口或原生语义通道。多屏逐一显式观察；隐藏、被遮挡或软件内部数据不能由像素完整恢复。

本次交付是按需远程帧 + ASIL，不包含实时视频预览/人工接管 UI。复用当前 Pi 审批，依然在真实用户桌面执行；没有额外 OS 或后台常驻帧缓存。整屏采集和输入仍须 macOS/Windows 实机验收，编译通过不能证明控制任务成功。

### 可选浏览器接入

模型不能自行打开调试端口或选择配置。用户先准备隔离测试浏览器/显式批准的调试会话，再停止 Runtime，在实际运行配置（默认 `~/.micromatrix-pi-mcp/runtime.json`，或 `MICROMATRIX_CONFIG_FILE` 指定文件）的 `computerUse` 中保留已有设置并添加：

```json
{
  "enabled": true,
  "allowActions": true,
  "browser": {
    "endpoint": "ws://127.0.0.1:9222/devtools/browser/替换为真实会话ID",
    "allowedOrigins": ["https://example.com/"]
  }
}
```

只支持显式 loopback CDP WebSocket；CDP 只是 Playwright 连接浏览器的底层传输，不替代 ASIL 状态/动作合同，也不用于读取普通原生软件。配置 URL 不允许凭据或 query；origin 填根 URL。浏览器重启后 WebSocket ID 会变化，需要在插件页的浏览器连接表单更新配置；不自动管理浏览器生命周期。独立 stdio 启动可使用 `--browser-configuration 'JSON'`。不配置则不注册 browser、不扫描用户浏览器、不自动启动或下载浏览器。退出断开连接，不关闭用户浏览器进程。

DOM 最多 300 个元素、ARIA 16 KiB，仅顶层 DOM，不保证完整 iframe/shadow tree；隐藏字段值不返回，命名敏感控件不提供动作/值，可见安全控件阻止截图并省略 ARIA。普通文字、作者标签或像素仍可能含秘密，这不是完整 DLP。导航检查 origin 并拒绝跨域重定向；页面子资源与未管理 popup 不构成网络沙箱。

macOS 窗口截图只在显式请求时读取，要求该 Computer Use helper 的“屏幕录制”授权；在原生授权窗口点击对应按钮请求。AX 动作仍只需“辅助功能”，不自动申请屏幕录制。Windows 使用目标窗口 PrintWindow，不回退全屏采集，自绘/受保护窗口可能空白或拒绝；输入不穿过锁屏/UAC，不自动提权。帧上限 1280px、384 KiB JPEG，浏览器 viewport 上限 1920px。执行前比对新的像素与结构化 revision、目标前台状态和输入安全状态；不是原子检查，动画可能触发 STALE_OBSERVATION，必须新观察，不能关闭校验或盲目重试。macOS 文本以有界 Unicode 片段发送、保留字素与 surrogate pair，不操作剪贴板；目标框架可能忽略/自行翻译合成 Unicode，仍须回读确认。[Apple 键盘事件文档](https://developer.apple.com/documentation/coregraphics/cgevent/keyboardsetunicodestring(stringlength:unicodestring:))。

## ASIL 可选结构化增强

### 官方实现核对

2026-10-07 完整读取用户提供的 19 页论文，并下载官方仓库，核对协议、Adapter、softwaregen 的模型/生成/资格判定/审计/声明式执行/探测/证据报告，以及 Blender、SVG、ODF 的实际访问路径。参考版本固定为 `sharryXR/ASIL@ca7706c87a0b1184c99623691adafed7693e25d3`；这次只做源码审阅，没有安装或执行上游程序，没有对真实软件做动作测试。[官方仓库](https://github.com/sharryXR/ASIL/tree/ca7706c87a0b1184c99623691adafed7693e25d3)。

官方不只有论文中的接口设想，而是两部分可参考实现：

| 官方模块 | 实际实现 | 本项目应如何使用 |
| --- | --- | --- |
| `protocol.py`、`adapter.py` | 六字段观察、带类型和约束的元素、语义动作、observe/validate/execute；还有文档克隆与 GUI 同步/渲染扩展点 | 建立显式协议映射，保留当前 MCP token、审批和 OS 代理，不把同名字段当成兼容 |
| `softwaregen/models.py`、`qualification.py` | OnboardingProfile、InterfacePlan、ExtensionBundle；按接口证据判定 direct_declarative / bridge_assisted / out_of_scope | 以经过用户/宿主审查的接口资料和权限为接入边界，不把一个 TS 回调当作完整接入流程 |
| `softwaregen/generator.py`、`audit.py` | 生成计划后确定性组装适配包、动作 Schema、薄 Adapter wrapper 和报告；审计证据引用、JSON Pointer、参数模板、端点与程序权限 | TS 移植声明式模型、组装及审计；模型输出只是候选，不能新增主机、程序、文件或凭据权限 |
| `softwaregen/runtime.py` | DeclarativeAdapter 直接解释 JSON 文件、JSON 命令输出与普通 HTTP API；按 Pointer 映射对象，按类型化参数模板构造命令/API 请求 | 应接入软件已有接口，不要求软件先实现本项目的 `/state`、`/action` 或 CAS 回执 |
| `softwaregen/validation.py`、`evidence.py` | 默认只读探测；显式允许才执行动作；记录观察哈希、状态变化、产物哈希与来源证据 | 建立独立回读和可复现验收；不要把 HTTP 成功、动作回执或状态哈希变化等同于任务完成 |
| `adapters/`、`action_schemas/`、`eval/raw_validation.py` | 已有论文 15 个软件适配器、动作例子，以及与观察构建分离的原始状态校验路径 | 参考并按需移植格式/软件访问逻辑及测试，不重新发明所有桥接，也不宣称所有适配器由生成器自动生成 |

来源：[软件扩展架构](https://github.com/sharryXR/ASIL/blob/ca7706c87a0b1184c99623691adafed7693e25d3/docs/software-extension-architecture.md)、[声明式执行器](https://github.com/sharryXR/ASIL/blob/ca7706c87a0b1184c99623691adafed7693e25d3/src/asil/softwaregen/runtime.py)、[接入模型](https://github.com/sharryXR/ASIL/blob/ca7706c87a0b1184c99623691adafed7693e25d3/src/asil/softwaregen/models.py)。

### 已移植范围与协议映射

npm 包的 `src/softwaregen/` 已提供 TS/Zod 的 Profile / Plan / Bundle 模型、资格判定、确定性组装、静态审计、声明式 Runtime、批准注册表和主机探测。`models / templates / audit / runtime / generation` 按上述官方源码移植；`bindings / io / registry` 是产品运行边界。上游许可、来源版本和变更声明随 npm 包发布，打包时从该依赖的 `third_party/asil/` 复制进桌面通知资源及内部服务归档，不增加公开 Release 的独立服务资产。

| 接入机制 | 本轮实现 | 仍未实现 |
| --- | --- | --- |
| JSON 文件 | 按官方 View / Pointer 映射已存在的工作区 JSON；有界读取、真实路径检查、原始探测数据 revision | SVG / ODF 等非 JSON 格式；GUI 未保存编辑与同步 |
| 结构化命令 / 原生脚本入口 | 直接解释固定程序与 argv/stdin 模板、JSON 输出；程序绝对路径绑定、通用解释器固定脚本前缀与哈希检查 | Blender 等真实软件适配、发现/版本兼容和活跃进程内桥接 |
| 服务 API | 直接解释 GET / POST / PUT / PATCH / DELETE、query/body、类型化模板；支持空成功响应 | WebSocket、自动认证刷新、软件专有条件写入合同 |
| 接入交付 | 本机 CLI 组装/审计/只读探测；显式批准注册表导入；现有内置 Computer Use 通过 Pi 加载 | 桌面适配包管理表单、AI 计划提议工具、Docker 探测与完整部署证据汇总 |

保留 `micromatrix-asil/1` 的 MCP 包装，而不是声称逐字兼容上游 Observation：

- 支持软件生成模型中的六类动作，包括 `api_call / batch`。上游元素的操作名称放入 `metadata.operations`，由 Plan 转成 `available_actions` 动作类型；`data_type / constraints` 可携带。View 映射为 navigation 数组，仍报告当前视图、来源、范围和截断。
- 动作参数使用上游 `{operation,arguments}`，固定软件级 `target` 来自经审查的操作声明；创建动作不必指向已存在控件。其他 Provider 没有此声明时仍必须操作已观察对象，安全控件不能因此绕过。
- `expect_observation` 接受上游 boolean，同时保留本产品的预期值校验对象；无论 boolean 是否为 false，产品都独立回读，不把动作回执当完成证据。所有 MCP 动作仍需新的观察 token、启用控制与既有 Pi 审批；不增加可让模型安装/修改权限的工具。
- 声明式 API 没有强制 `expected_revision / accepted_revision` RPC。执行前重查 raw probe revision，执行后独立查询；这不是原子 CAS，外部写入者可能在预检查之后修改。能力明确报告 `atomic_preconditions=false`。409/412 返回真实 precondition 失败，不自动重试。
- TS 组装使用 `sorted-json-js/1` 哈希；不将 Python `1.0` 的序列化哈希与 JS `1` 混为一谈。上游 Bundle 的 provenance 作为来源数据保留，不伪称已重验其 Python 哈希；安装授权绑定的是整个文件原始字节 SHA-256，CLI 的 `artifact_sha256` 就是此值。

已删除未交付的 `SemanticBridgeAdapter / StructuredCommandBridge / ServiceApiBridge` 专有 RPC 实现及对应冒烟入口，改用官方声明式合同；共享 Registry、token、审批、缓存检索和状态回读继续保留。

### 本机组装、批准与 Pi 接入

先人工准备/审查 Profile 和 Plan；`assemble` 不请求模型、不运行目标程序，也不授予候选包权限：

```sh
npm run asil -- assemble /absolute/profile.json /absolute/plan.json /absolute/private/new-extension
npm run asil -- audit /absolute/private/new-extension/extension.json
```

输出 `extension.json / action_schema.json / generation_report.json`，拒绝覆盖已有输出目录。只有通过审计、用户审查并批准运行权限后，才加入独立的本机注册表：

```json
{
  "schema_version": "1.0",
  "extensions": [{
    "enabled": true,
    "bundle": "/absolute/private/new-extension/extension.json",
    "sha256": "填写 assemble 返回的 artifact_sha256，64 位十六进制",
    "permissions": {
      "filesystem_root": "/absolute/document-workspace",
      "base_url": "https://approved-service.example"
    },
    "environment_refs": {
      "SOFTWAREGEN_GITEA_URL": "MY_GITEA_URL",
      "SOFTWAREGEN_GITEA_TOKEN": "MY_GITEA_TOKEN"
    }
  }]
}
```

路径和 URL 是说明占位符，必须改成已审查的实际值；Windows 使用实际绝对路径，例如 `C:/Users/name/...`。每个条目默认 disabled；启用包的注册表、Bundle、受信任脚本必须在全部已批准文档工作区之外，防止文档写入工具修改执行权限。Bundle 字节或脚本内容变化会拒绝加载/执行，必须重新审查更新哈希。

命令包还需 `permissions.executables`，按 Profile 的程序名绑定实际绝对路径。通用解释器需固定、无模板的脚本前缀，并在 `permissions.integrity` 中给出对应绝对脚本路径和 SHA-256；程序绑定及脚本由用户/宿主安装，不由网页 AI 下载。命令调用 shell=false，不继承全部服务秘密，限 argv/stdin/stdout/stderr、超时与取消；macOS 终止所属进程组，Windows 用 taskkill 终止所属 PID 树。它不是 OS 沙箱，批准前仍需审阅固定脚本和参数效果。

HTTP 接入必须同时匹配 Profile 的 allowed_hosts、解析后的 base URL 与用户批准的精确 base URL；HTTPS 为默认，仅明确允许的 loopback HTTP 可用，不跟随重定向。路径参数单段编码，禁止 traversal/路径分隔符；敏感 Header 使用私有变量引用，不进能力/追踪/原始错误。映射结果脱敏私有运行变量及命名秘密字段。文件最多 1 MiB、观察最多 2000 个对象；超限返回错误而非隐藏截断成功。

```sh
npm run asil -- probe /absolute/private/registry.json SOFTWARE_ID
```

CLI probe 只读，不支持动作旗标。程序 API 的 `probeExtension` 仅供受信任宿主隔离验收，带动作时必须显式 allowActions；它不替代网页 MCP 的审批。

内置 Computer Use 从现有运行配置中的 `computerUse.asilRegistry` 读取注册表路径；`computerUse.environmentRefs` 显式选择父服务向 MCP 子进程传递的变量名引用，注册表再通过 environment_refs 选择所需值，不写入秘密明文。例如在保留其他运行配置的前提下：

```json
{
  "computerUse": {
    "enabled": true,
    "allowActions": true,
    "asilRegistry": "/absolute/private/registry.json",
    "environmentRefs": {"MY_GITEA_URL": "MY_GITEA_URL", "MY_GITEA_TOKEN": "MY_GITEA_TOKEN"}
  }
}
```

修改配置时先停止 Runtime；配置和启用开关不会读取目标状态、启动 MCP/目标程序/Tunnel 或弹出 OS 权限。点击启动后才加载；再在网页端刷新工具，通过 `computer_capabilities → computer_targets → computer_observe → computer_validate → computer_act` 使用。独立 MCP 配置也可显式传入 `--asil-registry ABSOLUTE_FILE`，配合已有环境引用和 `--allow-actions`。未启用控制始终只读。

### 验收与后续任务

后续优先验收通用批量执行和混合通道的 macOS/Windows 实机交互，再完善浏览器配置 UI；SVG/ODF、原生脚本、活跃 GUI 同步与适配包管理是可选结构化增强。官方 BlenderAdapter 的 `blender --background --python` 操作保存的 `.blend` 文件，本轮没有复制成“控制当前未保存窗口”的承诺；软件原生解释器与产品级 Python 服务是两回事。AX/UIA 仍不代表完整软件状态；通用视觉回退必须显式选择，Linux 客户端仍不支持。

## 能力发现与按需读取

1. `computer_capabilities({})` 返回每个已注册 Provider 的 `id / source / description`；description 包含作用域、目标示例、边界与动作参数 JSON Schema。查询能力不会启动原生 helper。
2. `computer_targets({"adapter":"json"})` 只发现所选 Provider；省略 adapter 时发现全部。单个 Provider 不可用不会吞掉其他目标，失败出现在 `errors`，明确选择该 Provider 可取得原始错误。没有未知 Provider 的隐式回退。
3. `computer_observe` 仍接受 `{adapter,target}`；adapter 从能力发现选择，不再是代码里写死的二选一。观察 token 与 revision 的原有规则不变。
4. `computer_inspect` 从现有观察中检索标签/ID/类型，可按子树、可编辑性和是否有动作筛选，每页最多 100 个。它不重新读取目标、不延长有效期、不消耗或替换 token、不启动 helper，不申请权限。`query` 为字面量匹配，不执行正则/代码、不搜索隐藏字段；分页只覆盖本次已捕获的节点，不能恢复未暴露或截断节点。

```json
{
  "observation_id": "替换为真实观察 UUID",
  "query": "Status",
  "actionable": true,
  "limit": 20,
  "offset": 0
}
```

返回 `elements / total_matches / next_offset / revision / coverage`，后续用 next_offset 继续读取同一观察。`root` 为已观察的真实节点 ID，包含自身和后代；`type` 为精确类型匹配。安全控件不返回。

每个观察的 `meta.coverage` 明确区分来源范围、元素数及 `truncated`（未报告时为 null）；`complete_internal_state` 固定为 false，不承诺完整软件状态。`environment` 保留原生限制及截断原因。macOS AX / Windows UIA 都输出上限、深度、时间与显示文本长度；JSON 的元素截断与单个值的 `metadata.value_truncated` 分开报告。`truncated=false` 只说明未触发捕获边界，不代表目标软件完整暴露了内部状态。

Desktop 额外输出原生实际提供的只读属性：macOS 的 focused / selected / fullscreen / minimized / expanded 和 bounds；Windows 的 focused / offscreen / selected / window_state 和 bounds。不支持的属性省略，不猜值。Windows 最大化状态不等于 macOS fullscreen。desktop 的几何信息仅用于观察与验证；显式 desktop-visual 才增加有界窗口截图和输入。

### Provider 扩展契约

经审查的 TS 实现提供 `id / source / describe / capabilities / targets / observe / validateAction / execute / close`，由宿主传入 ComputerUseRuntime 的 Provider 列表；stdio 宿主也可通过 `startComputerUseMcp({workspace, providers:[...]})` 注入。describe 的动作 Schema 是发现信息，执行时仍必须由实现严格检查参数、目标、revision 和可用操作；仅声明能力不等于获得执行权限。

注册拒绝重复/非法/保留 ID。观察进入缓存前验证统一状态结构、唯一元素 ID、子节点引用、最多 2000 个节点及 1 MiB 总量；返回观察与内部缓存隔离，调用方不能修改观察来篡改后续校验。全部 Provider 共用只读模式、顺序执行、token、取消、审批接入和追踪，不在每个软件里再造模型或业务引擎。原生系统分支仍由 DesktopProxy 选择。

扩展当前是受信任源码接入与构建打包，不动态执行模型给出的文件路径、Workspace 插件或下载脚本；也不是完整 OS 沙箱。已经提供批准注册表与 softwaregen 声明式导入；尚未提供 UI 自助安装 Provider、浏览器连接配置表单、真实软件原生桥接或模型驱动的 softwaregen 计划生成服务。可选浏览器 DOM Provider 已按上述显式配置接入。第三方 MCP 仍可通过已有 Pi MCP 插件管理接入。

## macOS 授权身份

执行程序为随主应用打包的 `Contents/Helpers/micromatrix Computer Use.app`，固定 Bundle ID `org.micromatrix.computer-use`，保留原图标，并有独立权限窗口。TS 通过 LaunchServices 启动它，以私有 Unix socket 传递受限 ABI；不再将裸 helper 作为主程序子进程直接启动。每个连接使用临时 0700 目录、0600 握手文件与一次性随机 token；辅助应用核对当前用户的 IPC 对端。检测与实际控制使用同一应用身份，关闭连接时清理所属进程及通道，不终止目标应用。

只给 `micromatrix agent.app` 或 Blender 开启权限不等于授权 Computer Use 应用。在插件页点击“设置权限”，一键打开系统设置与持续存在的独立授权窗口并请求系统提示，不再请求后立即退出 helper。若系统未列出应用，用户直接将窗口中的应用卡片拖入权限列表，再开启开关，无须路径或快捷键。卡片使用实际 Bundle URL 的原生文件拖放，不创建副本或切换执行路径；只允许 copy、不移动应用包，不控制系统设置 UI。为 **micromatrix Computer Use** 开启“辅助功能 / 设备控制和数据访问”。删除条目后可再次点击此按钮；若系统没有重新列出，高级手动备用：用原生窗口的“复制添加目录”选中嵌入的 `.app` 并复制其父目录。在系统设置点“+”，按 ⌘⇧G 粘贴目录，再单击该 `.app` 后添加；不要把完整 `.app` 路径当成要进入的目录，也不要进入它的 Contents。[Apple 跳转文件夹快捷键](https://support.apple.com/en-us/102650)。路径对应当前运行的安装包，不是固定指向 `/Applications`，不要混用旧本地构建和安装版。返回后手动点击“重新检测”；旧连接仍报权限错误时手动停止并启动 Runtime。不会代点授权或修改 TCC 数据库；屏幕录制只在用户点击原生窗口对应按钮或明确调用 scope=screen_recording 的权限工具时请求，不申请完全磁盘访问。[Apple 辅助功能授权说明](https://support.apple.com/en-mo/guide/mac-help/mh43185/mac)。

正常启动、权限检查、停止及重新启动只运行现有应用，不重新编译、复制或签名。新 PID/临时 IPC 路径不等于新授权身份。本地回归检查启停前后的指定签名要求不变。

开发版使用 `org.micromatrix.computer-use.dev`，系统名称为 **micromatrix Computer Use Dev**；正式版保持 `org.micromatrix.computer-use`。服务编译时固定期望身份，运行环境和模型参数不能切换它；握手不匹配会拒绝连接。开发应用即使由同一证书签名，也不与正式版共用授权记录。

已发布的 v0.5.18 是 ad-hoc：其身份绑定具体构建 hash，不能保证更新后复用旧授权。本机真实日志曾把本地开发 hash `254672…` 当作正式版身份，安装版 `7f06a9…` 因签名不匹配被拒绝。这不是应让用户每次启动删条目的正常流程。修复后的正式发布使用固定长期自签名代码签名证书，不要求 Apple Developer ID 或 Team ID。签名要求是固定 identifier 加 certificate leaf 指纹；CI 验证证书用途、有效期与私钥身份，打包后核对主应用和 helper 的实际证书、稳定 DR，不接受 ad-hoc/cdhash 绑定。证书只在首次明确运行生成脚本时创建，应用启动及发布流程从不重新生成。配置和备份见 README。

首次从旧 ad-hoc 迁移可能需重新授权一次。两次不同构建的签名身份稳定不等于已证明所有 macOS 的 TCC 更新复用：实际授权 → 安装更新 → MCP observe 的验收仍待用户完成。自签名没有 Apple 公证，不替客户端安装可信根、不修改 TCC、不关闭 Gatekeeper。Tauri updater 的 minisign 密钥不是代码签名证书。[Apple 签名身份与信任策略](https://developer.apple.com/library/archive/technotes/tn2206/)。

## 浏览器连接配置

插件页 Computer Use 卡片的“浏览器连接”折叠区保存本地 `ws://127.0.0.1:PORT/devtools/browser/ID` 地址和允许的网站（每行一个 origin）。使用独立 Chromium 调试会话，不连接个人 profile；端点不会自动续期或隐式启动浏览器。保存/关闭通道只持久化配置，不连接 MCP、启动 Runtime 或申请系统权限。Runtime 停止后才能修改；无效端点拒绝且保留输入草稿。

连接将在用户显式 Start 后通过原有 Pi MCP 插件传给同一 Computer Use 服务。调试会话重新启动导致地址变化时，需要更新配置。模型只能操作 allowlist 内网页；跨 origin 重定向继续拒绝。配置错误不会把系统权限状态伪装为未授权。

## 已实现范围

| 适配器 | 状态来源 | 动作 | 边界 |
| --- | --- | --- | --- |
| `desktop` | macOS Accessibility：运行应用、控件角色/标签/值/可用操作 | 激活已观察应用；设置可写值；执行控件声明的 press / show_menu / raise | 必须授予辅助功能权限；不是完整内部状态；不支持安全输入框、坐标点击、任意键鼠注入或启动未观察应用 |
| `remote-desktop` | 选定显示器整屏 + 可见窗口布局 + 前台 AX/UIA | 原生语义；已观察显示器内点击/滚动；有限前台文本/键盘 | 显式整屏采集；多屏分别选择；前台结构并非所有软件内部状态；画面可包含其他窗口的秘密，无完整 DLP |
| `desktop` (Windows) | UI Automation 控件树与运行窗口 | Value/RangeValue 设置；Invoke/Toggle/SelectionItem/ExpandCollapse 语义操作；激活已观察应用 | Windows 10/11 x64，.NET Framework 4.8；锁屏、UAC 安全桌面、密码控件拒绝，不自动提权 |
| `desktop-visual` | 前台窗口截图 + 原生语义；macOS 可附 OCR | 原生语义动作、窗口内点击/滚动、有限按键和文本输入 | macOS 14+、辅助功能与屏幕录制；Windows 窗口渲染有限；拒绝安全输入/前台变化，非原子检查 |
| `browser` | 配置过的网页 DOM / ARIA，可选截图 | Playwright click / fill / press / scroll / goto | 显式 loopback 调试连接 + origins；顶层 DOM 有界，无任意 evaluate、浏览器启动或自动认证 |
| `json` | Workspace 内现有 JSON 与完整内容 revision | 修改已观察叶子，保留其他数据并原子替换文件 | 非隐藏、非凭证命名的 .json，最大 256 KiB；不创建任意文件，不代表 GUI 未保存状态 |

**Linux 客户端暂不支持**：桌面代理与原生构建明确拒绝，CI 不生成 Linux 安装包或 updater 条目。不删除历史发布包。Windows 后端已实现并接入构建，使用 Microsoft Roslyn / C#5 和 .NET Framework 4.8 引用实际交叉编译通过；本轮没有 Windows 实机，不能把编译或共用代理测试当成 Windows UIA 操作验收。macOS 与 Windows 使用相同 MCP 工具/参数/审批/回读逻辑，模型不选择系统分支。

观察包含 `meta / app_state / interactive_elements / environment / navigation / data_summary`，附带 revision。控件有 ID、值、子节点及允许动作；值可能截断/脱敏。AX / UIA ID 只在当前 helper 会话内有效，不能跨重启复用；JSON 目标使用 JSON Pointer，例如 `json:/status`。

## 接入当前程序

1. 安装包含独立 Computer Use 应用的新构建。已发布的 v0.5.17 仍使用裸 helper，不包含本轮授权身份修复。
2. 插件页已有 **Computer Use · 内置 Pi MCP 插件**，无需添加、填写程序路径或参数，默认关闭。显式打开开关只保存启用标志，**不启动 Runtime/Tunnel，也不弹 OS 授权**。
3. 插件页首次读取缓存状态，不自动启动 helper 检查权限。启用开关或明确点击“重新检测”才做无提示检查；“设置权限”才发起 TCC 提示。主界面 Computer Use 卡片仅显示开关、权限状态和操作按钮，移除连接详情、路径、Bundle ID 与授权教程。macOS 授权与目录复制由 Swift 原生窗口承担，Windows 仅显示“重新检测”，不启动 macOS 引导。Computer Use 与 MCP/Skills 卡片不再定时轮询或在窗口获得焦点时刷新；页面顶部“刷新”手动更新所有卡片，不清空正在编辑的配置、不重建卡片。打开设置不等于授权成功。
4. 权限就绪后仍由用户点击 Runtime 启动；启动也会无提示检查信任状态。Windows 检查 unlocked interactive desktop，明确高权限/UAC 边界，无自动提权、无伪造 macOS 设置入口。JSON 操作不要求 Accessibility 授权，GUI 观察/动作仍被 OS 阻止。
5. 网页 AI 连接现有公网 MCP，首次启用后在 ChatGPT Home/MCP 管理页 **刷新工具**，再发起请求；工具名以实际 tools/list 为准。OS 权限与现有 open_world 逐次审批独立，不能自动跳过。

旧官方预填 MCP 自动迁移为内置开关，保留 enabled/readonly；未点击保存前只在内存归一化，不改原配置或秘密。当前安装重新派生程序/工作区参数，不执行旧包路径。用户自定义的同名第三方服务不覆盖、不偷换；需先改其 ID。旧只读项必须明确点击“启用控制动作”才升级。

危险模式会自动放行；“会话批准”按既有 open_world 权限放行该认证会话的后续操作，不是只批准一个按钮。保存、打开软件和控制面启动都不启动 Computer Use MCP；只有 Runtime 显式启动才加载内置 stdio 子进程。明确发起的权限检测是独立的短生命周期 helper 检查，不连接 MCP、不读取应用内容；授权设置窗口则由用户打开，持续存在直到用户关闭，与检测和 MCP 的 IPC 会话隔离。同一桌面实例重复点击权限按钮时复用已有授权会话，不重复创建窗口。连接测试仅发现工具并清理，不调用权限工具。停止时 Pi 关闭连接和 owned 子进程树，MCP helper 随之关闭。

不独立监听 HTTP 端口，也不新增 Tunnel / OAuth。

### macOS 授权

先调用 `computer_permissions({"request":false})`，仅检查，不弹系统权限。若 accessibility=false：

- 用户在 **系统设置 → 隐私与安全性 → 辅助功能** 授权返回路径对应的 **micromatrix Computer Use.app**；不是主应用或目标 Blender。
- 可明确批准 `computer_permissions({"request":true})` 请求系统提示；仅启用动作后允许，不会自动授予权限。
- 授权后必要时停止并重启 Runtime，重新观察。AX-only 不请求屏幕录制；视觉通道需显式调用 `{request:true,scope:"screen_recording"}` 或使用原生权限窗口按钮。

**工具审批与 OS 授权是不同的两层权限**，不能靠批准工具绕过 TCC。未授权时 observe 返回真实 ACCESSIBILITY_PERMISSION_REQUIRED，不把空状态当成功。ad-hoc 开发包更新后可能需要再次确认系统信任，未承诺跨版本 TCC 授权永久保留。

### Windows 权限

computer_permissions 返回 interactive_desktop、elevated 和原生 helper 路径，没有 macOS 的 TCC 弹框。request=true 也不会提权、改 UIAccess 或操作 UAC；用户必须已解锁交互桌面。普通进程通常不能控制高权限/受保护目标，UIA provider 也可能只读或缺少模式；原样报告拒绝，不自动降级；显式 desktop-visual 的有限 SendInput 仍不绕过此权限边界。Windows 定位使用同一 pid:PID，控件 ID 为 uia:运行时ID。范围值会按原生最小/最大值检查，字符串值回读按字符串比较。依据 [Microsoft UIA 模式](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview) 和 [TreeWalker](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/navigate-among-ui-automation-elements-with-treewalker)。

## 工具合同

| 工具 | 用途 |
| --- | --- |
| computer_capabilities | 已注册 Provider、来源、作用域、动作参数 Schema、边界和动作启用状态 |
| computer_targets | 可选 adapter；发现失败隔离，不启动目标应用 |
| computer_permissions | 无提示检查；仅 macOS 显式请求 scope=accessibility / screen_recording |
| computer_observe | `{adapter:已注册ID, target:发现的目标}`；含覆盖范围与截断情况 |
| computer_inspect | 现有观察的子树/类型/标签/动作筛选与分页；不重新捕获 |
| computer_validate | 无副作用检查 schema、观察目标、revision；不是批准或执行 |
| computer_act | 单次批准的语义/视觉动作，回读并报告独立验证结果 |
| computer_run | 一段受限 async JavaScript；串行批量调用 computer / browser API，第一处失败停止 |
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

expect_observation 的对象形式默认比较 value，向后兼容已有请求；boolean 形式仍会回读，但不指定任务断言；也可指定 property 为 label / type / editable。验证原生属性使用 `{target:真实节点ID, property:"metadata", key:"fullscreen", value:true}`，属性缺失或不相符均为 failed，不将激活应用当成全屏成功。

validate 的 revision 拒绝返回 `details`，只包含发生变化的节点 ID、字段名和数量，不包含前后文本/值。act 被原生层以 STALE_OBSERVATION 拒绝时，可做一次只读诊断回捕获并保留原始错误，标注 `diagnostic_phase=after_rejection`；这不是执行时刻的精确现场，也不是自动重试。仍保留整体 revision 检查，没有未经验证地放宽为目标级检查。

超时、控件消失、进程退出、原生错误均返回 MCP isError=true 与错误码，结果可能未知。**不要自动重试发送/删除/提交**，先重新观察。没有自动寻找 Shell 或改换交互通道的替代路径。

## 运行和打包

Computer Use 固定依赖 `@ouvren/computer-use@0.1.1`；lockfile 固定 npm tarball 和 integrity。npm 包已包含 macOS ARM64、macOS Intel x64 和 Windows x64 原生 helper，workbench 只复制对应二进制，不调用 Swift/C# builder，也不在应用启动时下载/编译。缺失或架构不符立即拒绝打包，无本地源码回退。macOS helper 的部署目标为 13.0，桌面最低版本同步为 13.0；显式窗口截图仍需 macOS 14.0+。这些版本声明不是低版本实机验收。开发版和正式版由宿主重新封装并签名，正式版仍要求固定长期证书。

```bash
npm run typecheck
npm run prepare:computer-use  # 复制 npm 预编译 helper 并签名；Linux 拒绝
npm run dev:computer-use     # stdio MCP，默认只读，需 MCP Client 连接
npm run dev:computer-use -- --allow-actions --workspace /absolute/path/to/workspace
npm run build:sidecar        # 构建当前系统 SEA 与资源
```

QuickJS WASM 嵌入 SEA；Playwright 静态 JS/资源/许可随桌面包放在 automation/playwright-core，不含浏览器。服务启动不安装依赖。Windows 使用 npm 包预编译的固定 .NET Framework 4.8 x64 .exe，不在宿主构建/使用时运行 C# 编译器、PowerShell 或模型代码。宿主仅通过包的公开 API 组合 MCP 与固定安装路径；权限检测、MCP 和 SEA 使用同一个 helper，不读用户保存的可执行路径。桌面构建自动准备当前 OS helper，经 tauri.macos.conf.json / tauri.windows.conf.json 加入应用；macOS 不引用 Windows .exe，Windows 不引用 Swift 二进制。发布时保留许可证、最终代码签名及升级包签名检查，不启动 GUI fixture、浏览器会话或模拟 MCP 动作。

项目不保留测试目录、smoke 脚本、fixture 或测试运行器；CI/发布仅执行类型检查、构建和发布完整性校验。

## 验收边界与后续

授权交互参考 [OpenAI Work with Apps](https://help.openai.com/en/articles/10119604-work-with-apps-on-macos) 的启用/检查/引导方式和 [Apple 辅助功能授权说明](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac)，不是复刻其闭源实现或宣称支持其全部应用。

- macOS/Windows 的编译或打包成功不等于真实截图、DPI、TCC、键鼠或浏览器控制验收通过。操作需要用户授权及独立观察，不能把动作回执当作任务成功。
- UI 文本/文档是不可信数据而非指令。敏感字段/命名值脱敏不是完整 DLP，普通标签和文本仍可能包含私密数据；只观察授权应用，公网保持认证与审批。
- 路径校验、revision 和原子写入不是 OS 沙箱，不能完全消除本机恶意进程 TOCTOU race。
- AX/UIA、DOM 与视觉是互补来源，不保证任意软件都能暴露完整内部数据。模型选通道，执行器不替它猜测任务；深层接口仍通过批准 Provider 归一化，不在核心按软件名称硬编码，也不靠宿主“万能 eval”。
- 自定义适配器当前由产品源码实现并打包，不自动执行 Workspace 中未经审查的 TS 插件。

两项原有高危依赖告警已修复：MCP SDK 升级到 1.32.1，source-map-js 固定到 1.2.2；`npm audit` 为 0。外部 MCP OAuth 凭据必须保留 SDK 的授权服务器 issuer 绑定；旧的无绑定凭据自动清除，需重新登录一次，其他秘密配置保留。CI 保留依赖漏洞扫描，但不再运行 OAuth 或 sourcemap 的功能回归；既有 issuer 绑定与输入限制继续由产品代码执行。[SDK advisory](https://github.com/advisories/GHSA-6qxp-vccf-f47h)、[source-map-js advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)。
