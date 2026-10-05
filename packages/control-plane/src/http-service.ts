import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { isIP } from "node:net";

import { DesktopCommandRouter, UnsupportedDesktopCommandError } from "./commands.js";
import type { ControlPlaneOptions, DesktopApiRequest } from "./types.js";

const MAX_BODY_BYTES = 1024 * 1024;
const ALLOWED_ORIGINS = new Set([
  "http://127.0.0.1:5173",
  "http://localhost:5173",
  "http://tauri.localhost",
  "https://tauri.localhost",
  "tauri://localhost",
]);

function isLoopback(host: string): boolean {
  if (host === "localhost" || host === "::1") return true;
  return isIP(host) === 4 && host.startsWith("127.");
}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  const body = JSON.stringify(value) ?? "null";
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": Buffer.byteLength(body) });
  response.end(body);
}

async function readRequest(request: IncomingMessage): Promise<DesktopApiRequest> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY_BYTES) throw new Error("Desktop API request is too large");
    chunks.push(buffer);
  }
  const value: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!value || typeof value !== "object") throw new Error("Desktop API request must be an object");
  const method = Reflect.get(value, "method");
  const args = Reflect.get(value, "args");
  if (typeof method !== "string" || !Array.isArray(args)) {
    throw new Error("Desktop API request requires method and args");
  }
  return { method, args };
}

export class ControlPlaneHttpService {
  readonly #options: ControlPlaneOptions;
  readonly #router: DesktopCommandRouter;
  readonly #server;

  constructor(options: ControlPlaneOptions) {
    if (!isLoopback(options.host)) throw new Error("Control plane must bind to a loopback address");
    this.#options = options;
    this.#router = new DesktopCommandRouter(options);
    this.#server = createServer((request, response) => void this.#handle(request, response));
  }

  get localBaseUrl(): string {
    const host = this.#options.host === "::1" ? "[::1]" : this.#options.host;
    const address = this.#server.address();
    const port = address && typeof address === "object" ? address.port : this.#options.port;
    return `http://${host}:${port}`;
  }

  async start(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.#server.once("error", reject);
      this.#server.listen(this.#options.port, this.#options.host, () => {
        this.#server.off("error", reject);
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    if (!this.#server.listening) return;
    await new Promise<void>((resolve, reject) =>
      this.#server.close((error) => (error ? reject(error) : resolve())),
    );
  }

  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    response.setHeader("cache-control", "no-store");
    let host: URL;
    try { host = new URL(`http://${request.headers.host ?? ""}`); }
    catch { writeJson(response, 403, { error: "host_not_allowed" }); return; }
    const port = new URL(this.localBaseUrl).port;
    if (!["localhost", "127.0.0.1", "[::1]"].includes(host.hostname) || host.port !== port || host.username || host.password) {
      writeJson(response, 403, { error: "host_not_allowed" }); return;
    }
    const origin = request.headers.origin;
    if (origin && !this.#allowsOrigin(origin)) {
      writeJson(response, 403, { error: "origin_not_allowed" });
      return;
    }
    if (origin) {
      response.setHeader("access-control-allow-origin", origin);
      response.setHeader("vary", "origin");
    }
    if (request.method === "OPTIONS") {
      response.setHeader("access-control-allow-methods", "POST, OPTIONS");
      response.setHeader("access-control-allow-headers", "content-type");
      response.writeHead(204).end();
      return;
    }
    const url = new URL(request.url ?? "/", this.localBaseUrl);
    if (url.pathname === "/healthz") {
      writeJson(response, 200, { ok: true, process_id: process.pid });
      return;
    }
    if ((request.method === "GET" || request.method === "HEAD") && this.#serveWeb(url.pathname, request, response)) return;
    if (url.pathname !== "/api/desktop" || request.method !== "POST") {
      writeJson(response, 404, { error: "not_found" });
      return;
    }
    // WebView2 reports the explicitly trusted Tauri origin as cross-site.
    // Origin was validated above; Fetch Metadata must not break desktop clients.
    if (request.headers["content-type"]?.split(";")[0]?.trim().toLowerCase() !== "application/json"
      || (request.headers["sec-fetch-site"] === "cross-site" && !origin)) {
      writeJson(response, 415, { error: "json_same_site_required" }); return;
    }
    try {
      writeJson(response, 200, await this.#router.dispatch(await readRequest(request)));
    } catch (error) {
      const status = error instanceof UnsupportedDesktopCommandError ? 501 : 400;
      writeJson(response, status, {
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  #allowsOrigin(origin: string): boolean {
    if (ALLOWED_ORIGINS.has(origin) || origin === this.localBaseUrl) return true;
    // Permit loopback aliases of the configured control listener, never a Host
    // header supplied by the request. This also handles custom control ports.
    const base = new URL(this.localBaseUrl);
    if (this.#options.host === "localhost" || this.#options.host === "127.0.0.1") {
      return origin === `http://localhost:${base.port}` || origin === `http://127.0.0.1:${base.port}`;
    }
    return false;
  }

  #serveWeb(pathname: string, request: IncomingMessage, response: ServerResponse): boolean {
    const assets = this.#options.webAssets;
    if (!assets || Object.keys(assets).length === 0) return false;
    const key = pathname === "/" ? "/index.html" : pathname;
    const asset = assets[key] ?? (pathname.startsWith("/api/") ? undefined : assets["/index.html"]);
    if (!asset) return false;
    const body = Buffer.from(asset.bodyBase64, "base64");
    response.writeHead(200, {
      "content-type": asset.contentType,
      "content-length": body.length,
      "cache-control": key === "/index.html" ? "no-cache" : "public, max-age=31536000, immutable",
    });
    response.end(request.method === "HEAD" ? undefined : body);
    return true;
  }
}
