import { createHash } from "node:crypto";
import type { ExtensionFactory } from "@earendil-works/pi-coding-agent";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import { ExternalMcpError, type McpConnectionConfig } from "@micromatrix/plugin-kit";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { getDefaultEnvironment } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolResultSchema, ToolListChangedNotificationSchema, type CallToolResult, type Tool } from "@modelcontextprotocol/sdk/types.js";
import { OwnedStdioTransport } from "./stdio.js";
import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";

export { McpAuthStore } from "./auth.js";

export function exposedMcpName(server: string, tool: string): string {
  const readable = tool.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 22);
  return `mcp__${server}__${readable}_${createHash("sha256").update(tool).digest("hex").slice(0, 8)}`;
}

function resolveHeader(value: string, values: Readonly<Record<string, string>> = {}): string {
  return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_match, name: string) => {
    const resolved = (Object.hasOwn(values, name) ? values[name] : undefined) ?? (Object.hasOwn(process.env, name) ? process.env[name] : undefined);
    if (!resolved) throw new Error(`Missing service environment variable: ${name}`);
    if (/[\r\n]/.test(resolved)) throw new Error(`Invalid header environment variable: ${name}`);
    return resolved;
  });
}

/** Owned by one Pi extension session; never created while merely saving config. */
export class McpConnection {
  readonly client = new Client({ name: "micromatrix-pi-extension", version: "0.1.0" });
  readonly config: McpConnectionConfig;
  readonly options: McpOptions;
  #tools: readonly Tool[] = [];
  #refresh: Promise<readonly Tool[]> | undefined;
  #closing = false;
  #refreshAgain = false;
  #transport: OwnedStdioTransport | StreamableHTTPClientTransport | undefined;
  #connected = false;
  constructor(config: McpConnectionConfig, options: McpOptions = {}) {
    this.config = config; this.options = options;
    this.client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
      if (this.#refresh) { this.#refreshAgain = true; return; }
      try { await this.refresh(); } catch { /* refresh fails closed and reports status */ }
    });
  }

  async connect(workspace: string): Promise<readonly Tool[]> {
    this.options.signal?.throwIfAborted();
    const signal = this.options.signal ? AbortSignal.any([AbortSignal.timeout(30_000), this.options.signal]) : AbortSignal.timeout(30_000);
    const config = this.config;
    const env = getDefaultEnvironment();
    for (const [target, source] of Object.entries(config.envRefs)) {
      const value = (this.options.values && Object.hasOwn(this.options.values, source) ? this.options.values[source] : undefined) ?? (Object.hasOwn(process.env, source) ? process.env[source] : undefined);
      if (value === undefined) throw new Error(`Missing service environment variable: ${source}`);
      Object.defineProperty(env, target, { value, enumerable: true, configurable: true, writable: true });
    }
    const transport = config.transport === "stdio"
      ? new OwnedStdioTransport(config.command, config.args, env, workspace)
      : new StreamableHTTPClientTransport(new URL(config.url), {
        ...optionsAuth(this.options),
        ...(this.options.signal && this.options.fetch ? { fetch: (input, init) => this.options.fetch!(input, {
          ...init, signal: init?.signal ? AbortSignal.any([init.signal, this.options.signal!]) : this.options.signal!,
        }) } : {}),
        requestInit: { headers: Object.fromEntries(Object.entries(config.headers).map(([key, value]) => [key, resolveHeader(value, this.options.values)])) },
      });
    this.#transport = transport;
    this.client.onclose = () => {
      this.#connected = false;
      if (!this.#closing) { this.options.onStatus?.("disconnected", "Connection closed; stop and start Runtime to reconnect"); this.options.onTools?.([]); }
    };
    try {
      // SDK 1.30 has a sessionId optional-property declaration mismatch under
      // exactOptionalPropertyTypes; both concrete classes implement Transport.
      await this.client.connect(transport as Transport, { timeout: 15_000, signal });
      this.#connected = true;
      this.options.onStatus?.("connected", "");
      return await this.refresh();
    } catch (error) { await this.close(); throw error; }
  }

  refresh(): Promise<readonly Tool[]> {
    if (!this.#connected || this.#closing) return Promise.reject(new Error("MCP connection is not active"));
    if (this.#refresh) return this.#refresh;
    const work = this.#discover().catch(error => {
      if (!this.#closing) {
        this.#tools = []; this.options.onTools?.([]);
        this.options.onStatus?.("error", "MCP tool discovery failed; old tools revoked. Refresh or reconnect");
      }
      throw error;
    }); this.#refresh = work;
    void work.finally(() => {
      if (this.#refresh === work) this.#refresh = undefined;
      if (this.#refreshAgain && !this.#closing) { this.#refreshAgain = false; void this.refresh().catch(() => this.options.onStatus?.("error", "MCP tool discovery failed")); }
    }).catch(() => {});
    return work;
  }
  async #discover(): Promise<readonly Tool[]> {
    const deadline = Date.now() + 30_000, signal = AbortSignal.timeout(30_000);
    const tools: Tool[] = [], cursors = new Set<string>(); let cursor: string | undefined;
    do {
      if (Date.now() >= deadline || cursors.size >= 32) throw new Error("MCP discovery exceeded its time or pagination limit");
      const result = await this.client.listTools(cursor ? { cursor } : {}, { timeout: Math.min(15_000, deadline - Date.now()), signal });
      tools.push(...result.tools);
      if (tools.length > 500) throw new Error("MCP server exceeds the 500-tool limit");
      cursor = result.nextCursor;
      if (cursor && cursors.has(cursor)) throw new Error("MCP server repeated its pagination cursor");
      if (cursor) cursors.add(cursor);
    } while (cursor);
    if (this.#closing || !this.#connected) throw new Error("MCP closed during discovery");
    if (new Set(tools.map(tool => tool.name)).size !== tools.length) throw new Error("MCP server returned duplicate tool names");
    if (new Set(tools.map(tool => exposedMcpName(this.config.id, tool.name))).size !== tools.length) throw new Error("MCP exposed tool names collide; rename upstream tools");
    if (JSON.stringify(tools) !== JSON.stringify(this.#tools)) { this.#tools = tools; this.options.onTools?.(tools); }
    this.options.onStatus?.("connected", "");
    return tools;
  }

  async call(name: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<CallToolResult> {
    if (!this.#connected) throw new Error(`MCP ${this.config.id} disconnected; stop and start Runtime to reconnect`);
    if (!this.#tools.some(tool => tool.name === name)) throw new Error("MCP tool removed or discovery failed; refresh the tool list");
    return CallToolResultSchema.parse(await this.client.callTool({ name, arguments: args }, CallToolResultSchema,
      { timeout: 60_000, ...(signal ? { signal } : {}) }));
  }

  async close(): Promise<void> {
    this.#closing = true;
    this.#connected = false;
    await this.client.close().catch(() => undefined);
    await this.#transport?.close().catch(() => undefined);
    this.#transport = undefined;
  }
}

export interface McpOptions {
  signal?: AbortSignal;
  values?: Readonly<Record<string, string>>;
  authProvider?: OAuthClientProvider;
  fetch?: typeof fetch;
  onTools?: (tools: readonly Tool[]) => void;
  onStatus?: (status: string, message: string) => void;
}
function optionsAuth(options: McpOptions) {
  return { ...(options.authProvider ? { authProvider: options.authProvider } : {}), ...(options.fetch ? { fetch: options.fetch } : {}) };
}
export interface McpExtensionController { refresh(): Promise<readonly Tool[]>; close(): Promise<void> }
export function createMcpExtension(config: McpConnectionConfig, options: McpOptions = {},
  onCatalog?: (names: readonly string[]) => void, attach?: (controller: McpExtensionController) => void): ExtensionFactory {
  return (pi) => {
    let connection: McpConnection | undefined;
    const register = (tools: readonly Tool[]) => {
      for (const tool of tools) {
        const name = exposedMcpName(config.id, tool.name);
        pi.registerTool({
          name, label: `${config.name}: ${tool.title ?? tool.name}`,
          description: `[External MCP: ${config.name}] ${tool.description ?? tool.name}`,
          parameters: tool.inputSchema as AgentTool["parameters"],
          async execute(_id, params, signal) {
            const result = await connection!.call(tool.name, params as Record<string, unknown>, signal);
            // Pi expects failures to throw. MCP adapter retains the exact upstream result.
            if (result.isError) throw new ExternalMcpError(result);
            return {
              content: result.content.flatMap((part) => part.type === "text" || part.type === "image" ? [part] : [{ type: "text" as const, text: JSON.stringify(part) }]),
              details: { externalMcpResult: result },
            };
          },
        });
      }
      onCatalog?.(tools.map(tool => exposedMcpName(config.id, tool.name)));
    };
    pi.on("session_start", async (_event, ctx) => {
      connection = new McpConnection(config, { ...options, onTools: tools => { register(tools); options.onTools?.(tools); } });
      attach?.(connection);
      try { await connection.connect(ctx.cwd); }
      catch (error) { options.onStatus?.("error", "Connection failed; check credentials, OAuth login and executable path"); throw error; }
    });
    pi.on("session_shutdown", async () => { await connection?.close(); connection = undefined; });
  };
}
