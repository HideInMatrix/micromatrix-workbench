import type { AgentTool } from "@earendil-works/pi-agent-core";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { PluginRegistry } from "@micromatrix/plugin-kit";
import { describe, expect, it } from "vitest";

import { createProtocolServer } from "../src/index.js";

describe("Pi to MCP adapter", () => {
  it("lists and executes Pi AgentTools through MCP", async () => {
    const registry = new PluginRegistry({
      workspace: "/workspace",
      logger: { log() {} },
    });
    const double: AgentTool = {
      name: "double",
      label: "Double",
      description: "Double a number",
      parameters: {
        type: "object",
        properties: { value: { type: "number" } },
        required: ["value"],
      } as AgentTool["parameters"],
      execute: async (_id, input) => ({
        content: [{ type: "text", text: String(Number(input.value) * 2) }],
        details: undefined,
      }),
    };
    registry.register({ id: "math", displayName: "Math", createTools: () => [double] });

    const server = createProtocolServer(registry);
    const client = new Client({ name: "test", version: "1.0.0" });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    await client.connect(clientTransport);

    expect((await client.listTools()).tools.map(({ name }) => name)).toEqual(["double"]);
    expect(await client.callTool({ name: "double", arguments: { value: 21 } })).toMatchObject({
      content: [{ type: "text", text: "42" }],
    });

    await client.close();
    await server.close();
  });
});
