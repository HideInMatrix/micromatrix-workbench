import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isSea } from "node:sea";
import { createRequire } from "node:module";
import { parseExtensions, type ExtensionConfiguration, type McpConnectionConfig } from "@micromatrix/plugin-kit";

export interface ComputerUseConfiguration { readonly enabled: boolean; readonly allowActions: boolean }

/** Migrate only our old preset. Never enable a new builtin or reinterpret a custom MCP. */
export function builtinComputerUseConfiguration(value: unknown, extensions: ExtensionConfiguration) {
  const legacy = extensions.mcp.find(connection => connection.id === "computer_use"
    && connection.transport === "stdio" && connection.args.includes("--computer-use-mcp")
    && (connection.command === process.execPath || /^micromatrix-service(?:[.-]|$)/.test(basename(connection.command))));
  let configuration: ComputerUseConfiguration = { enabled: legacy?.enabled ?? false, allowActions: legacy ? legacy.args.includes("--allow-actions") : true };
  if (value !== undefined) {
    if (!value || typeof value !== "object" || Array.isArray(value)
      || typeof Reflect.get(value, "enabled") !== "boolean" || typeof Reflect.get(value, "allowActions") !== "boolean") throw new Error("Invalid built-in Computer Use configuration");
    configuration = { enabled: Reflect.get(value, "enabled"), allowActions: Reflect.get(value, "allowActions") };
  }
  return { configuration, extensions: parseExtensions({ ...extensions, mcp: extensions.mcp.filter(connection => connection !== legacy) }) };
}

/** The owned executable is derived on every run, never taken from saved/user MCP arguments. */
export function computerUseConnection(workspace: string, enabled = true, allowActions = false): McpConnectionConfig {
  const source = fileURLToPath(import.meta.url);
  const entry = source.endsWith(".cjs") ? source : join(dirname(source), source.endsWith(".ts") ? "main.ts" : "main.js");
  const args = isSea() ? [] : [...(entry.endsWith(".ts") ? ["--import", createRequire(import.meta.url).resolve("tsx")] : []), entry];
  return { id: "computer_use", name: "Computer Use · ASIL", enabled, transport: "stdio", command: process.execPath,
    args: [...args, "--computer-use-mcp", "--workspace", workspace, ...(allowActions ? ["--allow-actions"] : [])], url: "", envRefs: {}, headers: {} };
}
