import type { AgentTool } from "@earendil-works/pi-agent-core";
import { describe, expect, it } from "vitest";

import { PluginRegistry } from "../src/index.js";

function tool(name: string): AgentTool {
  return {
    name,
    label: name,
    description: `${name} tool`,
    parameters: { type: "object", properties: {} } as AgentTool["parameters"],
    execute: async () => ({ content: [{ type: "text", text: "ok" }], details: undefined }),
  };
}

const context = {
  workspace: "/workspace",
  logger: { log() {} },
};

describe("PluginRegistry", () => {
  it("registers tools by functional plugin", () => {
    const registry = new PluginRegistry(context);
    registry.register({ id: "files", displayName: "Files", createTools: () => [tool("read")] });

    expect(registry.ownerOf("read")).toBe("files");
    expect(registry.listTools().map(({ name }) => name)).toEqual(["read"]);
  });

  it("rejects tool ownership collisions", () => {
    const registry = new PluginRegistry(context);
    registry.register({ id: "one", displayName: "One", createTools: () => [tool("read")] });

    expect(() =>
      registry.register({ id: "two", displayName: "Two", createTools: () => [tool("read")] }),
    ).toThrow("already owned");
  });
});
