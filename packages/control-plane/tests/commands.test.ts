import { describe, expect, it, vi } from "vitest";

import { DesktopCommandRouter, type ControlPlaneOptions, type RuntimeSnapshot } from "../src/index.js";

function fixture() {
  let running = true;
  const snapshot = (): RuntimeSnapshot => ({
    runtimeId: "default",
    name: "Pi MCP Runtime",
    workspace: "/workspace",
    host: "127.0.0.1",
    port: 8234,
    running,
    publicMcpUrl: "http://127.0.0.1:8234/mcp",
    urlMode: "External URL",
    exitReason: "",
    networkProvider: "external",
    configuredPublicUrl: "http://127.0.0.1:8234",
    enableShell: false,
    oauthEnabled: false,
    rememberSecrets: true,
    permissionMode: "safe",
    networkOptions: {},
    pluginIds: ["workspace"],
    tools: [{ name: "read", description: "Read a file", inputSchema: { type: "object" }, pluginId: "workspace" }],
  });
  const options: ControlPlaneOptions = {
    appName: "MicroMatrix Pi MCP",
    version: "0.1.0",
    host: "127.0.0.1",
    port: 8233,
    runtime: {
      snapshot,
      start: vi.fn(async () => { running = true; }),
      stop: vi.fn(async () => { running = false; }),
      configure: vi.fn(async () => undefined),
      setPluginEnabled: vi.fn(async () => undefined),
    },
    logs: {
      entries: () => ({ cursor: 0, entries: [] }),
      clear: () => 0,
    },
  };
  return { options, router: new DesktopCommandRouter(options) };
}

describe("DesktopCommandRouter", () => {
  it("returns the singleton Pi runtime from bootstrap", async () => {
    const { router } = fixture();
    const result = await router.dispatch({ method: "bootstrap", args: [] });
    expect(result).toMatchObject({
      version: "0.1.0",
      runtime: { runtime_id: "default", running: true },
    });
  });

  it("stops the runtime without stopping the control plane", async () => {
    const { options, router } = fixture();
    const result = await router.dispatch({ method: "stop_runtime", args: [] });
    expect(options.runtime.stop).toHaveBeenCalledOnce();
    expect(result).toMatchObject({ running: false });
  });

  it("parses explicit secret update actions", async () => {
    const { options, router } = fixture();
    await router.dispatch({
      method: "configure_runtime",
      args: [{
        name: "Pi MCP Runtime",
        workspace: "/workspace",
        host: "127.0.0.1",
        port: 8234,
        permission_mode: "safe",
        remember_secrets: true,
        oauth_password_update: { action: "clear" },
        network: {
          provider: "cloudflare",
          public_url: "",
          options: { executable: "cloudflared", tunnel_token: "must-not-pass-as-plain-option" },
          secret_updates: { tunnel_token: { action: "set", value: "secret" } },
        },
      }],
    });

    expect(options.runtime.configure).toHaveBeenCalledWith(expect.objectContaining({
      oauthPassword: { action: "clear" },
      network: expect.objectContaining({
        options: { executable: "cloudflared" },
        secretUpdates: { tunnel_token: { action: "set", value: "secret" } },
      }),
    }));
  });

  it("rejects empty set operations", async () => {
    const { router } = fixture();
    await expect(router.dispatch({
      method: "configure_runtime",
      args: [{
        workspace: "/workspace",
        oauth_password_update: { action: "set", value: "" },
        network: { provider: "external", options: {}, secret_updates: {} },
      }],
    })).rejects.toThrow("oauth_password cannot be empty");
  });
});
