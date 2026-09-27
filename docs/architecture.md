# Architecture decisions

## AD-001: one brain

The remote/web AI model owns reasoning and tool selection. The local process
does not call an LLM. Pi is used for its audited tool implementations,
extension contract and execution behavior.

## AD-002: plugins are the unit of change

Every functional capability is a `BodyPlugin`. A plugin owns its tools and may
also install lifecycle behavior through Pi's official `ExtensionAPI`.

```text
BodyPlugin -> Pi AgentTool -> MCP tool
           -> Pi ExtensionAPI (optional)
```

MCP, tunnel and UI code cannot contain filesystem or shell implementations.

## AD-003: public transport is not execution

The MCP service binds locally. Network-provider plugins only publish that
origin and never inspect or execute MCP calls. Public mode fails closed unless
authentication is configured.

## AD-004: release pinning

Pi is pinned to release `v0.87.1` instead of tracking `main`. Upgrades require
tool-schema and behavior conformance tests.

## Delivery order

1. Pi workspace/shell plugins and registry.
2. Stateless Streamable HTTP MCP adapter.
3. External URL and Cloudflare tunnel providers.
4. OAuth and approval policy.
5. Minimal Vite status/configuration UI.
6. Additional ngrok, FRP and Tailscale provider plugins.
