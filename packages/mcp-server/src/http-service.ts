import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { randomUUID } from "node:crypto";
import { isIP } from "node:net";

import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { SUPPORTED_PROTOCOL_VERSIONS, type Implementation } from "@modelcontextprotocol/sdk/types.js";
import type { ToolExecutionContext, ToolExecutionGate } from "@micromatrix/approval";
import type { McpAuthorization } from "@micromatrix/oauth";
import type { PluginLogger, PluginRegistry } from "@micromatrix/plugin-kit";

import { createProtocolServer, DEFAULT_SERVER_INFO } from "./adapter.js";

export interface McpHttpServiceOptions {
  readonly host: string;
  readonly port: number;
  readonly authorization: McpAuthorization;
  readonly executionGate?: ToolExecutionGate;
  readonly registry: PluginRegistry;
  readonly logger: PluginLogger;
  readonly serverInfo?: Implementation;
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
  readonly instanceId = randomUUID();
  #publicBaseUrl: string | undefined;
  readonly #options: McpHttpServiceOptions;
  readonly #server;
  readonly #protocols = new Set<ReturnType<typeof createProtocolServer>>();

  constructor(options: McpHttpServiceOptions) {
    if (!isLoopback(options.host) && !options.authorization.protectsRequests) {
      throw new Error("Non-loopback MCP binding requires OAuth or a static Bearer token");
    }
    this.#options = options;
    this.#server = createServer((request, response) => {
      void this.#handle(request, response).catch((error: unknown) => {
        this.#options.logger.log("error", "HTTP request failed", { error: String(error) });
        if (response.destroyed || response.writableEnded) return;
        if (response.headersSent) response.destroy();
        else writeJson(response, 500, { error: "internal_error" });
      });
    });
  }

  async start(): Promise<void> {
    if (!isLoopback(this.#options.host) && !this.#publicBaseUrl) throw new Error("Non-loopback MCP binding requires an explicit public HTTPS origin before Start");
    await new Promise<void>((resolve, reject) => {
      this.#server.once("error", reject);
      this.#server.listen(this.#options.port, this.#options.host, () => {
        this.#server.off("error", reject);
        resolve();
      });
    });
    this.setPublicBaseUrl(this.#publicBaseUrl ?? this.localBaseUrl);
    this.#options.logger.log("info", "MCP server listening", {
      url: this.localMcpUrl,
      tools: this.#options.registry.listTools().map((tool) => tool.name),
    });
  }

  get localBaseUrl(): string {
    const host = this.#options.host === "::1" ? "[::1]" : this.#options.host;
    const address = this.#server.address();
    const port = address && typeof address === "object" ? address.port : this.#options.port;
    return `http://${host}:${port}`;
  }

  get localMcpUrl(): string {
    return `${this.localBaseUrl}/mcp`;
  }

  setPublicBaseUrl(value: string): void {
    const url = new URL(value);
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/" || !(url.protocol === "https:" || url.protocol === "http:" && isLoopback(url.hostname.replace(/^\[|\]$/g, "")))) throw new Error("Public MCP URL must be HTTPS or loopback HTTP with no extra path");
    this.#publicBaseUrl = url.origin;
    this.#options.authorization.setPublicOrigin?.(url.origin);
  }
  #allowedRequest(request: IncomingMessage): boolean {
    const host = request.headers.host;
    if (!host || /[\s/@?#\\]/.test(host)) return false;
    let url: URL; try { url = new URL(`http://${host}`); } catch { return false; }
    const local = new URL(this.localBaseUrl);
    const localHost = (isLoopback(url.hostname.replace(/^\[|\]$/g, "")) || url.hostname === local.hostname) && url.port === local.port;
    const publicHost = this.#publicBaseUrl && new URL(`${new URL(this.#publicBaseUrl).protocol}//${host}`).host === new URL(this.#publicBaseUrl).host;
    if (!localHost && !publicHost) return false;
    const origin = request.headers.origin;
    if (!origin) return true; // MCP clients usually run server-side.
    if (origin === this.#publicBaseUrl) return true;
    try { const parsed = new URL(origin); return parsed.origin === origin && parsed.protocol === "http:" && isLoopback(parsed.hostname.replace(/^\[|\]$/g, "")) && parsed.port === local.port; }
    catch { return false; }
  }

  async stop(): Promise<void> {
    if (!this.#server.listening) return;
    await Promise.all([...this.#protocols].map(protocol => protocol.close().catch(() => {})));
    await new Promise<void>((resolve, reject) => {
      this.#server.close((error) => (error ? reject(error) : resolve()));
      // Stop ingress before destroying remaining sockets: a stalled OAuth body
      // must not hold Runtime Stop/update hostage until Node's body timeout.
      this.#server.closeAllConnections();
    });
  }

  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    if (!this.#allowedRequest(request)) { writeJson(response, 403, { error: "host_or_origin_not_allowed" }); return; }
    const url = new URL(request.url ?? "/", this.localBaseUrl);
    if (await this.#options.authorization.handle(request, response, url)) return;
    if (url.pathname === "/") {
      response.setHeader("cache-control", "no-store");
      if (request.method !== "GET" && request.method !== "HEAD") {
        response.setHeader("allow", "GET, HEAD");
        writeJson(response, 405, { error: "method_not_allowed" });
        return;
      }
      if (request.method === "HEAD") {
        response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
        response.end();
        return;
      }
      const names = this.#options.registry.listTools().map((tool) => tool.name);
      const authorization = this.#options.authorization;
      // A public server card is not the local control plane. Keep URLs relative
      // so Quick Tunnel works without trusting Host or forwarded headers.
      writeJson(response, 200, {
        server: this.#options.serverInfo ?? DEFAULT_SERVER_INFO,
        supportedProtocolVersions: SUPPORTED_PROTOCOL_VERSIONS,
        transport: { type: "streamable_http", endpoint: "/mcp", methods: ["POST", "GET"] },
        auth: authorization.oauthEnabled
          ? {
              type: "oauth2", scheme: "Bearer",
              authorizationUrl: "/authorize", tokenUrl: "/token", clientRegistration: "cimd",
            }
          : authorization.protectsRequests
            ? { type: "bearer", scheme: "Bearer" }
            : { type: "none" },
        capabilities: { tools: { listChanged: true } },
        tools: { count: names.length, names },
      });
      return;
    }
    if (url.pathname === "/healthz") {
      writeJson(response, 200, {
        ok: true,
        instance_id: this.instanceId,
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

    if (request.method !== "POST" && request.method !== "GET") {
      response.setHeader("allow", "POST, GET");
      writeJson(response, 405, { error: "method_not_allowed" });
      return;
    }

    if (this.#protocols.size >= 64) { writeJson(response, 503, { error: "too_many_connections" }); return; }
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
    const protocol = createProtocolServer(
      this.#options.registry, this.#options.executionGate, executionContext, this.#options.serverInfo,
    );
    this.#protocols.add(protocol);
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
      this.#protocols.delete(protocol);
      await protocol.close().catch(() => undefined);
    }
  }
}
