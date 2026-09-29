import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { isIP } from "node:net";

import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { ToolExecutionContext, ToolExecutionGate } from "@micromatrix/approval";
import type { McpAuthorization } from "@micromatrix/oauth";
import type { PluginLogger, PluginRegistry } from "@micromatrix/plugin-kit";

import { createProtocolServer } from "./adapter.js";

export interface McpHttpServiceOptions {
  readonly host: string;
  readonly port: number;
  readonly authorization: McpAuthorization;
  readonly executionGate?: ToolExecutionGate;
  readonly registry: PluginRegistry;
  readonly logger: PluginLogger;
}

function isLoopback(host: string): boolean {
  if (host === "localhost" || host === "::1") return true;
  return isIP(host) === 4 && host.startsWith("127.");
}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(value));
}

export class McpHttpService {
  readonly #options: McpHttpServiceOptions;
  readonly #server;

  constructor(options: McpHttpServiceOptions) {
    if (!isLoopback(options.host) && !options.authorization.protectsRequests) {
      throw new Error("Non-loopback MCP binding requires OAuth or a static Bearer token");
    }
    this.#options = options;
    this.#server = createServer((request, response) => void this.#handle(request, response));
  }

  async start(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.#server.once("error", reject);
      this.#server.listen(this.#options.port, this.#options.host, () => {
        this.#server.off("error", reject);
        resolve();
      });
    });
    this.#options.logger.log("info", "MCP server listening", {
      url: this.localMcpUrl,
      tools: this.#options.registry.listTools().map((tool) => tool.name),
    });
  }

  get localBaseUrl(): string {
    const host = this.#options.host === "::1" ? "[::1]" : this.#options.host;
    return `http://${host}:${this.#options.port}`;
  }

  get localMcpUrl(): string {
    return `${this.localBaseUrl}/mcp`;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve, reject) =>
      this.#server.close((error) => (error ? reject(error) : resolve())),
    );
  }

  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const url = new URL(request.url ?? "/", this.localBaseUrl);
    if (await this.#options.authorization.handle(request, response, url)) return;
    if (url.pathname === "/healthz") {
      writeJson(response, 200, {
        ok: true,
        plugins: this.#options.registry.listPlugins().map(({ plugin }) => plugin.id),
        tools: this.#options.registry.listTools().map((tool) => tool.name),
      });
      return;
    }

    if (url.pathname !== "/mcp") {
      writeJson(response, 404, { error: "not_found" });
      return;
    }

    const principal = await this.#options.authorization.authorize(request, "/mcp");
    if (!principal) {
      response.setHeader("www-authenticate", this.#options.authorization.challenge(request, "/mcp"));
      writeJson(response, 401, { error: "unauthorized" });
      return;
    }

    if (request.method !== "POST") {
      response.setHeader("allow", "POST");
      writeJson(response, 405, { error: "method_not_allowed" });
      return;
    }

    // The SDK documents `undefined` as stateless mode, while its published
    // declaration currently conflicts with exactOptionalPropertyTypes.
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    } as never);
    const executionContext: ToolExecutionContext = {
      authentication: principal.authentication,
      subjectId: principal.subjectId,
      sessionId: principal.sessionId,
      ...(principal.clientId ? { clientId: principal.clientId } : {}),
      ...(principal.clientName ? { clientName: principal.clientName } : {}),
    };
    const protocol = createProtocolServer(this.#options.registry, this.#options.executionGate, executionContext);
    try {
      await protocol.connect(
        transport as unknown as Parameters<typeof protocol.connect>[0],
      );
      await transport.handleRequest(request, response);
    } catch (error) {
      this.#options.logger.log("error", "MCP request failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      if (!response.headersSent) writeJson(response, 500, { error: "internal_error" });
    } finally {
      await protocol.close().catch(() => undefined);
    }
  }
}
