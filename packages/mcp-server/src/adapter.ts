import { randomUUID } from "node:crypto";

import type { AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";
import type { ToolExecutionContext, ToolExecutionGate } from "@micromatrix/approval";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type Implementation,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { ExternalMcpError, type PluginRegistry } from "@micromatrix/plugin-kit";

export const DEFAULT_SERVER_INFO: Implementation = {
  name: "micromatrix-pi-body",
  version: "0.1.0",
};

export function toMcpTool(tool: AgentTool): Tool {
  return {
    name: tool.name,
    title: tool.label,
    description: tool.description,
    inputSchema: tool.parameters as Tool["inputSchema"],
  };
}

export function toMcpResult(result: AgentToolResult): CallToolResult {
  const details = result.details;
  if (details && typeof details === "object" && "externalMcpResult" in details) {
    return details.externalMcpResult as CallToolResult;
  }
  return {
    content: result.content.map((part) =>
      part.type === "text"
        ? { type: "text" as const, text: part.text }
        : { type: "image" as const, data: part.data, mimeType: part.mimeType },
    ),
  };
}

export function createProtocolServer(
  registry: PluginRegistry,
  gate?: ToolExecutionGate,
  executionContext?: ToolExecutionContext,
  serverInfo: Implementation = DEFAULT_SERVER_INFO,
): Server {
  const server = new Server(
    serverInfo,
    { capabilities: { tools: { listChanged: true } } },
  );

  const unsubscribe = registry.subscribe(() => { void server.sendToolListChanged().catch(() => {}); });
  server.onclose = unsubscribe;
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
      await gate?.authorize(request.params.name, request.params.arguments ?? {}, executionContext, extra.signal);
      if (registry.getTool(request.params.name) !== tool) throw new Error("Tool definition changed during approval; submit a new tool call");
      const result = await tool.execute(
        randomUUID(),
        request.params.arguments ?? {},
        extra.signal,
      );
      return toMcpResult(result);
    } catch (error) {
      if (error instanceof ExternalMcpError) return error.result as CallToolResult;
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
