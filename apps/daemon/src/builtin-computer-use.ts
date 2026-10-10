import { basename, dirname, join, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { isSea } from "node:sea";
import { createRequire } from "node:module";
import { parseExtensions, type ExtensionConfiguration, type McpConnectionConfig } from "@micromatrix/plugin-kit";
import { browserConfiguration, type BrowserConfiguration } from "@ouvren/computer-use";

export interface ComputerUseConfiguration { readonly enabled: boolean; readonly allowActions: boolean; readonly asilRegistry?: string; readonly environmentRefs?: Readonly<Record<string,string>>; readonly browser?: BrowserConfiguration }

/** Migrate only our old preset. Never enable a new builtin or reinterpret a custom MCP. */
export function builtinComputerUseConfiguration(value: unknown, extensions: ExtensionConfiguration) {
  const legacy = extensions.mcp.find(connection => connection.id === "computer_use"
    && connection.transport === "stdio" && connection.args.includes("--computer-use-mcp")
    && (connection.command === process.execPath || /^micromatrix-service(?:[.-]|$)/.test(basename(connection.command))));
  let configuration: ComputerUseConfiguration = { enabled: legacy?.enabled ?? false, allowActions: legacy ? legacy.args.includes("--allow-actions") : true };
  if (value !== undefined) {
    if (!value || typeof value !== "object" || Array.isArray(value)
      || typeof Reflect.get(value, "enabled") !== "boolean" || typeof Reflect.get(value, "allowActions") !== "boolean") throw new Error("Invalid built-in Computer Use configuration");
    const registry = Reflect.get(value, "asilRegistry"), environmentRefs = Reflect.get(value, "environmentRefs"), browser = Reflect.get(value,"browser");
    if (registry !== undefined && (typeof registry !== "string" || !isAbsolute(registry) || registry.includes("\0"))) throw new Error("ASIL registry must be an absolute local path");
    if (environmentRefs !== undefined && (!environmentRefs || typeof environmentRefs !== "object" || Array.isArray(environmentRefs)
      || Object.keys(environmentRefs).length > 64 || Object.entries(environmentRefs).some(([key, source]) =>
        !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || /^(NODE_OPTIONS|NODE_PATH|PYTHONPATH|PYTHONSTARTUP|LD_.*|DYLD_.*)$/i.test(key)
        || typeof source !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(source)))) throw new Error("Invalid explicit Computer Use environment references");
    configuration = { enabled: Reflect.get(value, "enabled"), allowActions: Reflect.get(value, "allowActions"),
      ...(registry !== undefined ? {asilRegistry: registry} : {}), ...(environmentRefs !== undefined ? {environmentRefs: {...environmentRefs as Record<string,string>}} : {}), ...(browser!==undefined?{browser:browserConfiguration.parse(browser)}:{}) };
  }
  return { configuration, extensions: parseExtensions({ ...extensions, mcp: extensions.mcp.filter(connection => connection !== legacy) }) };
}

/** The owned executable is derived on every run, never taken from saved/user MCP arguments. */
export function computerUseConnection(workspace: string, enabled = true, allowActions = false, settings?: Pick<ComputerUseConfiguration, "asilRegistry" | "environmentRefs" | "browser">): McpConnectionConfig {
  const source = fileURLToPath(import.meta.url);
  const entry = source.endsWith(".cjs") ? source : join(dirname(source), source.endsWith(".ts") ? "main.ts" : "main.js");
  const args = isSea() ? [] : [...(entry.endsWith(".ts") ? ["--import", createRequire(import.meta.url).resolve("tsx")] : []), entry];
  return { id: "computer_use", name: "Computer Use · ASIL", enabled, transport: "stdio", command: process.execPath,
    args: [...args, "--computer-use-mcp", "--workspace", workspace, ...(allowActions ? ["--allow-actions"] : []), ...(settings?.asilRegistry ? ["--asil-registry", settings.asilRegistry] : []), ...(settings?.browser?["--browser-configuration",JSON.stringify(settings.browser)]:[])],
    url: "", envRefs: {...settings?.environmentRefs}, headers: {} };
}
