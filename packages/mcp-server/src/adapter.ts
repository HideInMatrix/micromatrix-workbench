import { randomUUID } from "node:crypto";

import type { AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";
import type { ToolExecutionGate } from "@micromatrix/approval";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import type { PluginRegistry } from "@micromatrix/plugin-kit";

export function toMcpTool(tool: AgentTool): Tool {
  return {
    name: tool.name,
    title: tool.label,
    description: tool.description,
    inputSchema: tool.parameters as Tool["inputSchema"],
  };
}

export function toMcpResult(result: AgentToolResult): CallToolResult {
  return {
    content: result.content.map((part) =>
      part.type === "text"
        ? { type: "text" as const, text: part.text }
        : { type: "image" as const, data: part.data, mimeType: part.mimeType },
    ),
  };
}

export function createProtocolServer(registry: PluginRegistry, gate?: ToolExecutionGate): Server {
  const server = new Server(
    { name: "micromatrix-pi-body", version: "0.1.0" },
    { capabilities: { tools: { listChanged: false } } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: registry.listTools().map(toMcpTool),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    const tool = registry.getTool(request.params.name);
    if (!tool) {
      return {
        content: [{ type: "text", text: `Unknown tool: ${request.params.name}` }],
        isError: true,
      };
    }

    try {
      await gate?.authorize(request.params.name, request.params.arguments ?? {}, extra.signal);
      const result = await tool.execute(
        randomUUID(),
        request.params.arguments ?? {},
        extra.signal,
      );
      return toMcpResult(result);
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: error instanceof Error ? error.message : String(error),
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}
