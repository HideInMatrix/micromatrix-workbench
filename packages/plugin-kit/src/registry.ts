import type { AgentTool } from "@earendil-works/pi-agent-core";

import type { BodyPlugin, LoadedBodyPlugin, PluginContext } from "./types.js";

export class PluginRegistry {
  readonly #context: PluginContext;
  readonly #plugins = new Map<string, LoadedBodyPlugin>();
  readonly #tools = new Map<string, AgentTool>();

  constructor(context: PluginContext) {
    this.#context = context;
  }

  register(plugin: BodyPlugin): LoadedBodyPlugin {
    if (this.#plugins.has(plugin.id)) {
      throw new Error(`Plugin already registered: ${plugin.id}`);
    }

    const tools = Object.freeze([...plugin.createTools(this.#context)]);
    for (const tool of tools) {
      const owner = this.ownerOf(tool.name);
      if (owner) {
        throw new Error(`Tool ${tool.name} is already owned by plugin ${owner}`);
      }
    }

    const loaded = Object.freeze({ plugin, tools });
    this.#plugins.set(plugin.id, loaded);
    for (const tool of tools) this.#tools.set(tool.name, tool);
    return loaded;
  }

  listPlugins(): readonly LoadedBodyPlugin[] {
    return Object.freeze([...this.#plugins.values()]);
  }

  listTools(): readonly AgentTool[] {
    return Object.freeze([...this.#tools.values()]);
  }

  getTool(name: string): AgentTool | undefined {
    return this.#tools.get(name);
  }

  ownerOf(toolName: string): string | undefined {
    for (const [pluginId, loaded] of this.#plugins) {
      if (loaded.tools.some((tool) => tool.name === toolName)) return pluginId;
    }
    return undefined;
  }

  async dispose(): Promise<void> {
    for (const loaded of [...this.#plugins.values()].reverse()) {
      await loaded.plugin.dispose?.();
    }
    this.#tools.clear();
    this.#plugins.clear();
  }
}
