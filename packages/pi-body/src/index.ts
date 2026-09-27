import type { AgentTool } from "@earendil-works/pi-agent-core";
import type {
  ExtensionAPI,
  ExtensionFactory,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import type { BodyPlugin, PluginContext } from "@micromatrix/plugin-kit";

export function registerAgentTools(pi: ExtensionAPI, tools: readonly AgentTool[]): void {
  for (const tool of tools) {
    const definition: ToolDefinition = {
      name: tool.name,
      label: tool.label,
      description: tool.description,
      parameters: tool.parameters,
      execute: async (toolCallId, params, signal, onUpdate) =>
        tool.execute(toolCallId, params, signal, onUpdate),
    };
    pi.registerTool(definition);
  }
}

/** Build an official Pi extension from the same logical plugins exposed by MCP. */
export function createPiBodyExtension(
  plugins: readonly BodyPlugin[],
  context: PluginContext,
): ExtensionFactory {
  return async (pi) => {
    for (const plugin of plugins) {
      if (plugin.installPiExtension) await plugin.installPiExtension(pi, context);
      else registerAgentTools(pi, plugin.createTools(context));
    }
  };
}
