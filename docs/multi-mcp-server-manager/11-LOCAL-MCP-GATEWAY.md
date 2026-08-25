# Local MCP Gateway

Local MCP Gateway 用于同一台机器上，以**一个本地监听端口 + 多个独立 Public Hostname**承载多个 Workspace Profile。完整实现说明见 [`../LOCAL_MCP_GATEWAY.md`](../LOCAL_MCP_GATEWAY.md)。

## 当前模型

同一台机器的多个 Profile 使用独立 hostname，但可以全部回源到同一个本地端口：

```text
https://mcp.example.com/mcp
https://mcp-claude.example.com/mcp
https://mcp-codex.example.com/mcp
        ↓
Cloudflare Named Tunnel
        ↓
127.0.0.1:8234
        ↓
Local MCP Gateway
        ├─ Host: mcp.example.com         -> 主 Workspace Runtime
        ├─ Host: mcp-claude.example.com  -> Claude Runtime
        └─ Host: mcp-codex.example.com   -> Codex Runtime
```

Cloudflare Dashboard 可以在同一个 Named Tunnel 下配置多条 Published Application：

```text
mcp.example.com        -> http://127.0.0.1:8234
mcp-claude.example.com -> http://127.0.0.1:8234
mcp-codex.example.com  -> http://127.0.0.1:8234
```

每个 Profile 对外统一使用根路径 `/mcp`，OAuth issuer 也位于对应 hostname 根路径。`instance_path` 仅保留为本地兼容路由和旧配置迁移字段，不再作为新公网模型的 Profile 身份。

## 已实现能力

- 一个 Gateway Process 同时持有多个独立 Runtime。
- `Host -> profile_id` 公网路由；本机请求仍可使用 legacy `instance_path` 作为兼容路由。
- 每个 Profile 独立 Public Hostname、OAuth issuer、Registry、token secret 和 Desktop Permission Broker identity。
- MCP、OAuth、Authorization Server Metadata、Protected Resource Metadata 在每个 hostname 上都使用根路径。
- 一个 Named Tunnel 可以把多个 hostname 全部回源到同一个 `127.0.0.1:<port>`。
- 多 Workspace 新配置要求每个 Profile 填写独立 Public Hostname；Cloudflare 多 Workspace 使用 Named Tunnel，不使用 Quick Tunnel。
- 公网 E2E 按每个 Profile 的 hostname 验证 Runtime、OAuth metadata、401 challenge 和真实 Authorization Code + PKCE Token Exchange。

## URL 约定

以 Claude Profile 为例：

```text
MCP:
https://mcp-claude.example.com/mcp

Issuer:
https://mcp-claude.example.com

Authorize:
https://mcp-claude.example.com/oauth/authorize

Token:
https://mcp-claude.example.com/oauth/token

Protected Resource Metadata:
https://mcp-claude.example.com/.well-known/oauth-protected-resource/mcp

Authorization Server Metadata:
https://mcp-claude.example.com/.well-known/oauth-authorization-server
```

## 兼容旧配置

历史 Gateway 可能保存为共享 hostname + Path：

```text
https://mcp.example.com/claude/mcp
```

运行时仍保留 Path fallback，因此旧配置不会因为升级直接无法读取。用户在服务页面为该 Profile 填写独立 Public Hostname 并保存后，即进入新的 Host-based 模型；新建多 Workspace 服务不再允许缺少 Profile Hostname。

## 验收重点

1. 多个 hostname 可以同时指向同一个 `127.0.0.1:8234`。
2. `/mcp` 根据 Host 选择正确 Runtime，未知公网 Host 必须返回 404，不能落到主 Workspace。
3. 每个 Profile 的 Server Card endpoint 都是 `/mcp`。
4. 每个 Profile 的 OAuth issuer 与其独立 hostname 完全一致。
5. RFC 9728 resource 为 `https://<profile-host>/mcp`。
6. 不同 Profile 不共享 OAuth Registry、token secret、PermissionSession 或 Broker identity。
7. E2E 自检失败只告警，不关闭健康 Gateway。

