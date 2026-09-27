import { describe, expect, it } from "vitest";

import { normalizeBaseUrl, providerResult } from "../src/index.js";

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
