import { describe, expect, it } from "vitest";

import { ManagedProcess, normalizeBaseUrl, providerResult } from "../src/index.js";

const logger = { log() {} };

describe("network provider contracts", () => {
  it("normalizes MCP URLs to a stable public base", () => {
    expect(normalizeBaseUrl("https://agent.example.com/mcp/")).toBe("https://agent.example.com");
    expect(providerResult("external", "https://agent.example.com/mcp", "External")).toMatchObject({
      publicBaseUrl: "https://agent.example.com",
      publicMcpUrl: "https://agent.example.com/mcp",
    });
  });

  it("rejects non-http transports", () => {
    expect(() => normalizeBaseUrl("file:///tmp/socket")).toThrow("Unsupported");
  });
});

describe("ManagedProcess", () => {
  it("resolves when the child emits the expected readiness line", async () => {
    const managed = new ManagedProcess(logger);
    managed.start(process.execPath, ["-e", "console.log('ready')"], "fixture");
    await expect(managed.waitFor((line) => line === "ready", 2_000, "fixture readiness")).resolves.toBe("ready");
    await managed.stop();
  });

  it("rejects immediately when an executable cannot be spawned", async () => {
    const managed = new ManagedProcess(logger);
    managed.start("/definitely/missing/micromatrix-command", [], "missing");
    await expect(managed.waitFor(() => false, 10_000, "missing process")).rejects.toThrow("spawn error");
    await managed.stop();
  });
});
