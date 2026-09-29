# Architecture decisions

## AD-001: one brain

The remote/web AI model owns reasoning and tool selection. The local process does not call an LLM. Pi supplies its tool implementations, extension contract and execution behavior. This prevents two competing agent loops.

## AD-002: plugins are the unit of change

Every execution capability is a `BodyPlugin`. A plugin owns its tools and may install lifecycle behavior through Pi's official `ExtensionAPI`.

```text
BodyPlugin -> Pi AgentTool -> approval gate -> MCP tool
           -> Pi ExtensionAPI (optional)
```

MCP transport, Tunnel Provider and UI code do not implement filesystem or shell operations.

## AD-003: public transport is not execution

The MCP service binds locally. Network Provider plugins only publish that origin and never inspect or execute MCP calls. Public exposure fails closed unless OAuth or a compatibility bearer token is configured.

## AD-004: OAuth state is ephemeral

DCR clients, codes, access tokens and refresh tokens remain in process memory. Only the optional local consent password may be persisted, and only when the operator enables secret persistence. Authorization Code requires PKCE S256.

## AD-005: approval precedes Pi execution

The MCP adapter calls the approval policy before `AgentTool.execute`. Read-only tools are automatically allowed; write, shell and unknown/open-world operations follow the selected mode. UI approval receives redacted arguments and cannot expand Workspace path enforcement.

## AD-006: local control plane

The Vite/Tauri UI talks only to a loopback control API. The control plane owns configuration and lifecycle, while `/mcp` remains the protocol endpoint for web AI clients. A desktop instance manages one Runtime to keep lifecycle and persisted secrets unambiguous.

## AD-007: reproducible packaging

`build:service` compiles project references, builds Vite, embeds the static files, and emits one CJS service bundle. `build:sidecar` injects that bundle into a Node SEA binary for the current target. Tauri 2 ships the SEA as an external sidecar and terminates it when the app exits.

## AD-008: release pinning

Pi is pinned to release `v0.87.1` instead of tracking `main`. Upgrades require tool-schema and behavior conformance tests.

## Completed phase

1. Pi Workspace/Shell plugin registry.
2. Streamable HTTP MCP adapter.
3. OAuth metadata, DCR, PKCE, token refresh and revocation.
4. Tool approval and dangerous-operation modes.
5. External, Cloudflare, ngrok, FRP and Tailscale Providers.
6. Vite service state, plugin controls and Tunnel configuration.
7. Embedded static UI, Node SEA sidecar and Tauri 2 desktop shell.
