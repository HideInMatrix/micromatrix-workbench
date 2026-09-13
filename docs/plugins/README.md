# 插件

MicroMatrix Workbench 的“插件”页面是本地能力管理入口，不是第二套执行引擎。

当前插件模型只聚合已经存在的真实能力：

- **应用**：Workbench 自带的 System Tools / Host Capabilities，只读展示；
- **MCP**：用户保存的全局 MCP Connections，可配置、启用、停用、测试、发现工具和卸载；
- **技能**：用户保存的全局 Skills，可创建、编辑、验证和删除。

Capability Catalog 继续作为 AI-facing 的发现协议，类型固定为 `builtin_tool / mcp_tool / skill`。插件 UI 直接消费 Capability Catalog、MCP Connection Store 和 Skill Store，不维护第二份插件状态。

## 页面

```text
/plugins
  本机已安装入口、搜索、添加 Skill / MCP

/plugins/installed
  插件 / 应用 / MCP / 技能 分类管理

/plugins/mcp/:connectionId
  MCP 详情、连接状态、重连/断开、复制地址、测试、卸载

/plugins/skills/manage
  Skill 编辑器

/plugins/mcp/manage
  MCP Connection 编辑器
```

MCP 的连接状态操作必须写回真实 `enabled` 配置；重连/试用使用现有 MCP Connection Test，不伪造常驻连接状态。Skill 当前没有启停字段，UI 不提供虚假的 Skill Switch。

## 暂不实现

线上插件仓库尚未开发，因此当前版本不提供：

- 热门；
- 新品推荐；
- 分类市场推荐；
- 在线插件安装；
- 插件市场搜索；
- “来自插件”的远端 MCP 安装。

界面可以保留“浏览目录”的不可用提示，但不得用本地假数据模拟线上市场。

## 已删除的 Workflow 模型

产品不再提供 Workflow Definition、Workflow Engine、Workflow Run、Workflow Artifact Runtime、Workflow Approval、Vue Flow 编辑器以及对应 MCP tools/facades。AI Client 直接从 Capability Catalog 发现并调用 Tool、MCP Tool 或读取 Skill 方法。

