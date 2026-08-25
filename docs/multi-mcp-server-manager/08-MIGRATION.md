# 迁移策略

## 1. 旧配置来源

当前旧版本主要有：

- `settings.json` 中的单 Server Workspace、Password、Network 配置。
- `oauth/<public-url-hash>.clients.json`。
- `oauth/<public-url-hash>.token-secret`。

## 2. 首次升级

如果不存在 `servers.json`，但存在旧桌面 settings：

1. 自动创建一个 Server Profile。
2. 名称默认使用 `默认服务`。
3. server_id 新生成。
4. Workspace、Password、Network、Port 从旧配置迁移。
5. 不删除旧 settings，至少保留一个版本周期用于回滚。

## 3. OAuth Registry 迁移

如果旧配置拥有固定 `public_url`：

- 根据旧 URL 找到旧 hash Registry。
- 复制到新 `servers/<server_id>/oauth/`。
- 保留原文件，不直接删除。
- 同时迁移旧 `token-secret`，确保旧 client_id 对应的既有 access token 签名体系不会因为升级立即改变。
- 如果新目录中对应文件已经存在，则不覆盖，保证迁移幂等。

如果旧配置使用 Quick Tunnel：

- 不迁移旧随机 URL 的 OAuth Client。
- 新 Session 重新 DCR。

当前代码已实现上述迁移规则。

## 4. 幂等

迁移必须可重复执行而不会：

- 重复创建 Profile。
- 重复复制 Client。
- 覆盖已经存在的新 Server OAuth 数据。

## 5. 清理

旧文件清理由后续版本单独处理，不在首次重构中自动删除。

## 6. Gateway Path 模型迁移到独立 Hostname

历史多 Workspace Gateway 可能保存为：

```text
https://mcp.example.com/mcp
https://mcp.example.com/claude/mcp
```

升级后采用：

```text
https://mcp.example.com/mcp
https://mcp-claude.example.com/mcp
```

迁移规则：

- 旧 `instance_path` 字段继续读取，不立即删除。
- 主 Workspace 若没有成员级 `public_url`，自动沿用 Service 的 `network.public_url`。
- 子 Profile 若没有独立 `public_url`，继续以 legacy Path 模式运行，避免升级后直接失效。
- 用户在服务页面为子 Profile 填写独立 Public Hostname 并保存后，该 Profile 公网入口切换到 Host-based `/mcp`。
- 新建或重新保存的 `multi` Service 必须为每个 Profile 提供独立 Public Hostname。
- 旧 `instance_path` 在迁移后仍作为本地兼容路由保留，不再作为公网 OAuth issuer 的组成部分。
