import type { AgentTool } from "@earendil-works/pi-agent-core";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface PluginLogger {
  log(level: LogLevel, message: string, fields?: Readonly<Record<string, unknown>>): void;
}

export interface PluginContext {
  readonly workspace: string;
  readonly logger: PluginLogger;
}

/**
 * One functional unit shared by the Pi extension runtime and the MCP adapter.
 * `createTools` is authoritative: MCP exposes these tools directly, while
 * `installPiExtension` can add lifecycle guards or make the same feature
 * available when this plugin is loaded by a normal Pi session.
 */
export interface BodyPlugin {
  readonly id: string;
  readonly displayName: string;
  createTools(context: PluginContext): readonly AgentTool[];
  installPiExtension?(pi: ExtensionAPI, context: PluginContext): void | Promise<void>;
  dispose?(): void | Promise<void>;
}

export interface LoadedBodyPlugin {
  readonly plugin: BodyPlugin;
  readonly tools: readonly AgentTool[];
}
