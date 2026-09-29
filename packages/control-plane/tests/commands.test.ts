import { describe, expect, it, vi } from "vitest";

import { DesktopCommandRouter, type ControlPlaneOptions, type RuntimeSnapshot } from "../src/index.js";

function fixture() {
  let running = true;
  const snapshot = (): RuntimeSnapshot => ({
    serverId: "default",
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
    enabled: true,
    oauthEnabled: false,
    hasSavedPassword: false,
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
      setEnabled: vi.fn(async () => undefined),
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
  it("projects the Pi runtime into the reused desktop bootstrap contract", async () => {
    const { router } = fixture();
    const result = await router.dispatch({ method: "bootstrap", args: [] });
    expect(result).toMatchObject({
      version: "0.1.0",
      selected_server_id: "default",
      servers: [{ server_id: "default", running: true }],
    });
  });

  it("stops the runtime without stopping the control plane", async () => {
    const { options, router } = fixture();
    const result = await router.dispatch({ method: "stop_server", args: ["default"] });
    expect(options.runtime.stop).toHaveBeenCalledOnce();
    expect(result).toMatchObject({ running: false });
  });
});
