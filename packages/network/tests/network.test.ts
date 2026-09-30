import { describe, expect, it, vi } from "vitest";

import { assertExecutable, ManagedProcess, normalizeBaseUrl, providerResult } from "../src/index.js";

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
  it("preflights tunnel executables before spawning", async () => {
    await expect(assertExecutable(process.execPath)).resolves.toBeUndefined();
    await expect(assertExecutable("/definitely/missing/micromatrix-command")).rejects.toThrow("not found or not executable");
  });

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

  it("reports a process that exits after readiness", async () => {
    const managed = new ManagedProcess(logger);
    let failure: Error | undefined;
    managed.start(process.execPath, ["-e", "console.log('ready'); setTimeout(() => process.exit(7), 20)"], "fixture");
    await managed.waitFor((line) => line === "ready", 2_000, "fixture readiness");
    managed.monitorUnexpectedExit((error) => { failure = error; });
    await vi.waitFor(() => expect(failure?.message).toContain("code=7"));
    await managed.stop();
  });

  it("does not report an intentional stop as a failure", async () => {
    const managed = new ManagedProcess(logger);
    const failures: Error[] = [];
    managed.start(process.execPath, ["-e", "console.log('ready'); setInterval(() => {}, 1000)"], "fixture");
    await managed.waitFor((line) => line === "ready", 2_000, "fixture readiness");
    managed.monitorUnexpectedExit((error) => failures.push(error));
    await managed.stop();
    expect(failures).toEqual([]);
  });
});
