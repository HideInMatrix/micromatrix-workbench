import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { isIP } from "node:net";
import type { IncomingMessage, ServerResponse } from "node:http";

import type { LocalOAuthOptions, McpAuthorization, McpPrincipal } from "./types.js";
import { CimdClientResolver, CimdDiscoveryError } from "./cimd.js";

interface AuthorizationCode {
  readonly clientId: string;
  readonly clientName?: string;
  readonly redirectUri: string;
  readonly codeChallenge: string;
  readonly scope: string;
  readonly resource: string | undefined;
  readonly expiresAt: number;
}

interface TokenRecord {
  readonly clientId: string;
  readonly clientName?: string;
  readonly sessionId: string;
  readonly scope: string;
  readonly resource: string | undefined;
  readonly expiresAt: number;
}

const FORM_LIMIT = 64 * 1024;

class OAuthBodyTooLargeError extends Error {
  constructor() { super("OAuth request body is too large"); }
}

function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

function sameSecret(actual: string, expected: string): boolean {
  const left = Buffer.from(actual);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

function checkedOrigin(value: string): string {
  const url = new URL(value);
  const host = url.hostname.replace(/^\[|\]$/g, "");
  const loopback = host === "localhost" || host === "::1" || isIP(host) === 4 && host.startsWith("127.");
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/"
    || !(url.protocol === "https:" || url.protocol === "http:" && loopback)) throw new Error("OAuth public origin requires HTTPS or loopback HTTP with no path");
  return url.origin;
}

function normalizeResource(value: string): string | undefined {
  try {
    const url = new URL(value);
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return undefined;
  }
}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

function oauthError(response: ServerResponse, status: number, error: string, description: string): void {
  writeJson(response, status, { error, error_description: description });
}

async function readBody(request: IncomingMessage): Promise<string> {
  if (Number(request.headers["content-length"]) > FORM_LIMIT) {
    request.resume();
    throw new OAuthBodyTooLargeError();
  }
  let size = 0;
  const chunks: Buffer[] = [];
  // Keep the socket available to return a 413 even for chunked input.
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > FORM_LIMIT) {
      request.resume();
      throw new OAuthBodyTooLargeError();
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function redirectWith(url: string, values: Readonly<Record<string, string | undefined>>): string {
  const destination = new URL(url);
  for (const [key, value] of Object.entries(values)) if (value !== undefined) destination.searchParams.set(key, value);
  return destination.toString();
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[character] ?? character);
}

export class LocalOAuthServer implements McpAuthorization {
  readonly #options: Required<Pick<LocalOAuthOptions, "accessTokenTtlSeconds" | "refreshTokenTtlSeconds">> & LocalOAuthOptions;
  readonly #cimd = new CimdClientResolver();
  readonly #codes = new Map<string, AuthorizationCode>();
  readonly #accessTokens = new Map<string, TokenRecord>();
  readonly #refreshTokens = new Map<string, TokenRecord>();
  readonly #staticSessionId: string;
  #origin: string | undefined;
  #window = { until: 0, requests: 0, logins: 0 };
  #nextPrune = 0;
  readonly #requestLimit: number;
  readonly #loginLimit: number;
  readonly #stateLimit: number;

  constructor(options: LocalOAuthOptions) {
    this.#options = {
      ...options,
      accessTokenTtlSeconds: options.accessTokenTtlSeconds ?? 3_600,
      refreshTokenTtlSeconds: options.refreshTokenTtlSeconds ?? 30 * 24 * 3_600,
    };
    this.#origin = options.publicOrigin ? checkedOrigin(options.publicOrigin) : undefined;
    this.#requestLimit = options.limits?.requestsPerMinute ?? 240;
    this.#loginLimit = options.limits?.loginAttemptsPerMinute ?? 20;
    this.#stateLimit = options.limits?.maxStateEntries ?? 2048;
    for (const limit of [this.#requestLimit, this.#loginLimit, this.#stateLimit]) if (!Number.isSafeInteger(limit) || limit < 1 || limit > 10000) throw new Error("Invalid OAuth resource limit");
    for (const ttl of [this.#options.accessTokenTtlSeconds, this.#options.refreshTokenTtlSeconds]) if (!Number.isSafeInteger(ttl) || ttl < 1 || ttl > 365 * 24 * 3600) throw new Error("Invalid OAuth token TTL");
    this.#staticSessionId = options.staticBearerToken
      ? `static:${createHash("sha256").update(options.staticBearerToken).digest("hex").slice(0, 24)}`
      : "static:disabled";
  }

  /** Set by the owned listener/provider, never by Host/X-Forwarded-* input. */
  setPublicOrigin(origin: string): void { this.#origin = checkedOrigin(origin); }
  #publicOrigin(request: IncomingMessage): string {
    if (this.#origin) return this.#origin;
    // Standalone local use only. Public deployments must configure their origin.
    return checkedOrigin(`http://${request.headers.host ?? ""}`);
  }
  #prune(force = false): void {
    const now = Date.now();
    if (!force && now < this.#nextPrune) return;
    this.#nextPrune = now + 30000;
    for (const map of [this.#codes, this.#accessTokens, this.#refreshTokens]) for (const [key, value] of map) if (value.expiresAt <= now) map.delete(key);
  }
  #allowRequest(request: IncomingMessage, response: ServerResponse, login: boolean): boolean {
    const now = Date.now();
    if (now >= this.#window.until) this.#window = { until: now + 60000, requests: 0, logins: 0 };
    // Global quotas cannot be evaded with spoofed proxy IP headers, and are
    // bounded without an attacker-controlled per-address/client map.
    if (++this.#window.requests > this.#requestLimit || login && ++this.#window.logins > this.#loginLimit) {
      request.resume();
      response.setHeader("retry-after", String(Math.max(1, Math.ceil((this.#window.until - now) / 1000))));
      oauthError(response, 429, "temporarily_unavailable", "OAuth request limit reached; retry later");
      return false;
    }
    return true;
  }
  #tokenRoom(response: ServerResponse, rotating = false): boolean {
    this.#prune(true);
    if (this.#accessTokens.size >= this.#stateLimit || this.#refreshTokens.size >= this.#stateLimit + Number(rotating)) {
      oauthError(response, 503, "temporarily_unavailable", "OAuth token capacity reached; retry after existing tokens expire"); return false;
    }
    return true;
  }

  get oauthEnabled(): boolean {
    return Boolean(this.#options.password);
  }

  get protectsRequests(): boolean {
    return this.oauthEnabled || Boolean(this.#options.staticBearerToken);
  }

  async authorize(request: IncomingMessage, resourcePath: string): Promise<McpPrincipal | undefined> {
    this.#prune();
    const authorization = request.headers.authorization;
    let expectedResource: string | undefined;
    try { expectedResource = normalizeResource(`${this.#publicOrigin(request)}${resourcePath}`); } catch { return undefined; }
    if (!authorization?.startsWith("Bearer ")) {
      if (this.#options.staticBearerToken || this.oauthEnabled) return undefined;
      return {
        authentication: "anonymous",
        subjectId: "local-anonymous",
        sessionId: "local-anonymous",
        clientName: "Local client",
        scopes: ["mcp"],
        ...(expectedResource ? { resource: expectedResource } : {}),
      };
    }
    const token = authorization.slice("Bearer ".length);
    if (this.#options.staticBearerToken && sameSecret(token, this.#options.staticBearerToken)) {
      return {
        authentication: "static_bearer",
        subjectId: this.#staticSessionId,
        sessionId: this.#staticSessionId,
        clientName: "Static Bearer client",
        scopes: ["mcp"],
        ...(expectedResource ? { resource: expectedResource } : {}),
      };
    }
    const record = this.#accessTokens.get(token);
    if (!record) return undefined;
    if (record.expiresAt <= Date.now()) {
      this.#accessTokens.delete(token);
      return undefined;
    }
    const scopes = record.scope.split(/\s+/).filter(Boolean);
    if (!scopes.includes("mcp")) return undefined;
    const resource = record.resource ? normalizeResource(record.resource) : undefined;
    if (record.resource && (!resource || resource !== expectedResource)) return undefined;
    return {
      authentication: "oauth",
      subjectId: `oauth:${record.clientId}`,
      sessionId: record.sessionId,
      clientId: record.clientId,
      clientName: record.clientName ?? record.clientId,
      scopes,
      ...(resource ? { resource } : expectedResource ? { resource: expectedResource } : {}),
    };
  }

  challenge(request: IncomingMessage, resourcePath: string): string {
    const metadata = `${this.#publicOrigin(request)}/.well-known/oauth-protected-resource${resourcePath}`;
    return `Bearer resource_metadata="${metadata}", scope="mcp"`;
  }

  async handle(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean> {
    try {
      return await this.#route(request, response, url);
    } catch (error) {
      if (!(error instanceof OAuthBodyTooLargeError)) throw error;
      response.setHeader("connection", "close");
      oauthError(response, 413, "invalid_request", error.message);
      return true;
    }
  }

  async #route(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean> {
    if (!this.oauthEnabled) return false;
    const path = url.pathname;
    const known = ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-authorization-server", "/.well-known/openid-configuration", "/authorize", "/token", "/revoke"].includes(path);
    if (!known) return false;
    this.#prune();
    if (!this.#allowRequest(request, response, path === "/authorize" && request.method === "POST")) return true;
    if (path === "/.well-known/oauth-protected-resource" || path === "/.well-known/oauth-protected-resource/mcp") {
      this.#metadata(request, response);
      return true;
    }
    if (path === "/.well-known/oauth-authorization-server" || path === "/.well-known/openid-configuration") {
      this.#serverMetadata(request, response);
      return true;
    }
    if (path === "/authorize" && (request.method === "GET" || request.method === "POST")) {
      await this.#authorize(request, response, url);
      return true;
    }
    if (path === "/token" && request.method === "POST") {
      await this.#token(request, response);
      return true;
    }
    if (path === "/revoke" && request.method === "POST") {
      await this.#revoke(request, response);
      return true;
    }
    return false;
  }

  #metadata(request: IncomingMessage, response: ServerResponse): void {
    const origin = this.#publicOrigin(request);
    writeJson(response, 200, {
      resource: `${origin}/mcp`,
      authorization_servers: [origin],
      scopes_supported: ["mcp"],
      resource_name: "MicroMatrix Pi MCP",
    });
  }

  #serverMetadata(request: IncomingMessage, response: ServerResponse): void {
    const origin = this.#publicOrigin(request);
    writeJson(response, 200, {
      issuer: origin,
      authorization_endpoint: `${origin}/authorize`,
      token_endpoint: `${origin}/token`,
      client_id_metadata_document_supported: true,
      authorization_response_iss_parameter_supported: true,
      revocation_endpoint: `${origin}/revoke`,
      scopes_supported: ["mcp"],
      response_types_supported: ["code"],
      grant_types_supported: ["authorization_code", "refresh_token"],
      code_challenge_methods_supported: ["S256"],
      token_endpoint_auth_methods_supported: ["none"],
    });
  }

  async #authorize(request: IncomingMessage, response: ServerResponse, url: URL): Promise<void> {
    const params = new URLSearchParams(url.search);
    if (request.method === "POST") {
      for (const [key, value] of new URLSearchParams(await readBody(request))) params.set(key, value);
    }
    const clientId = params.get("client_id") ?? "";
    const redirectUri = params.get("redirect_uri") ?? "";
    const state = params.get("state") ?? undefined;
    let client;
    try { client = await this.#cimd.resolve(clientId); }
    catch (error) {
      // No opaque client IDs or registration fallback. No unverified redirect.
      if (error instanceof CimdDiscoveryError) oauthError(response, error.status, error.oauthError, error.message);
      else oauthError(response, 400, "invalid_client_metadata", "CIMD client_id URL, fetched JSON document or public-client authentication is invalid");
      return;
    }
    if (!client.redirect_uris.includes(redirectUri)) {
      oauthError(response, 400, "invalid_request", "Redirect URI is not listed in the CIMD document");
      return;
    }
    const challenge = params.get("code_challenge") ?? "";
    const issuer = this.#publicOrigin(request);
    if (params.get("response_type") !== "code" || params.get("code_challenge_method") !== "S256" || !/^[A-Za-z0-9_-]{43}$/.test(challenge)) {
      response.writeHead(302, { location: redirectWith(redirectUri, { error: "invalid_request", state, iss: issuer }) }).end();
      return;
    }
    if (request.method === "GET") {
      const action = escapeHtml(`${url.pathname}${url.search}`);
      const clientName = escapeHtml(client.client_name ?? client.client_id);
      const clientHost = /^https:/i.test(clientId) ? `<p>客户端元数据域名：${escapeHtml(new URL(clientId).hostname)}</p>` : "";
      const redirectHost = new URL(redirectUri).hostname;
      const callback = `<p>授权回调：${escapeHtml(redirectUri)}</p>`;
      const warning = ["localhost", "127.0.0.1", "[::1]"].includes(redirectHost) ? "<p>回调位于本机。客户端名称并不证明本机程序身份，仅授权你刚刚启动的可信客户端。</p>" : "";
      response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
      response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>授权 MCP</title><style>body{font:14px system-ui;background:#111827;color:#f9fafb;display:grid;place-items:center;min-height:100vh;margin:0}.card{width:min(420px,calc(100% - 40px));padding:24px;border:1px solid #374151;border-radius:12px;background:#1f2937;overflow-wrap:anywhere}input,button{box-sizing:border-box;width:100%;padding:11px;border-radius:8px;border:1px solid #4b5563;margin-top:12px}button{background:#2563eb;color:#fff;font-weight:600}</style><form class="card" method="post" action="${action}"><h1>授权 MCP 客户端</h1><p>${clientName} 请求访问本机 Pi 工具。</p>${clientHost}${callback}${warning}<input type="password" name="password" autocomplete="current-password" placeholder="OAuth 密码" required><button type="submit">授权连接</button></form></html>`);
      return;
    }
    const expected = this.#options.password ?? "";
    if (!sameSecret(params.get("password") ?? "", expected)) {
      response.writeHead(302, { location: redirectWith(redirectUri, { error: "access_denied", error_description: "Invalid password", state, iss: issuer }) }).end();
      return;
    }
    const resource = params.get("resource");
    if (resource && normalizeResource(resource) !== normalizeResource(`${issuer}/mcp`)) { oauthError(response, 400, "invalid_target", "Resource must identify this MCP service"); return; }
    if (params.get("scope") && params.get("scope") !== "mcp") { oauthError(response, 400, "invalid_scope", "Only mcp scope is supported"); return; }
    this.#prune(true);
    if (this.#codes.size >= this.#stateLimit) { oauthError(response, 503, "temporarily_unavailable", "OAuth code capacity reached; retry later"); return; }
    const code = randomToken();
    this.#codes.set(code, {
      clientId,
      ...(client.client_name ? { clientName: client.client_name } : {}),
      redirectUri,
      codeChallenge: challenge,
      scope: params.get("scope") || "mcp",
      resource: resource ?? `${issuer}/mcp`,
      expiresAt: Date.now() + 5 * 60_000,
    });
    response.writeHead(302, { location: redirectWith(redirectUri, { code, state, iss: issuer }) }).end();
  }

  async #token(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const params = new URLSearchParams(await readBody(request));
    if (request.headers.authorization || params.has("client_secret") || params.has("client_assertion") || params.has("client_assertion_type")) {
      oauthError(response, 400, "invalid_client", "Only public-client authentication (none) with PKCE is supported");
      return;
    }
    if (params.get("grant_type") === "authorization_code") {
      const codeValue = params.get("code") ?? "";
      const code = this.#codes.get(codeValue);

      const verifier = params.get("code_verifier") ?? "";
      const computed = createHash("sha256").update(verifier).digest("base64url");
      if (!/^[A-Za-z0-9._~-]{43,128}$/.test(verifier) || !code || code.expiresAt <= Date.now() || code.clientId !== params.get("client_id") || code.redirectUri !== params.get("redirect_uri") || !sameSecret(computed, code.codeChallenge)) {
        oauthError(response, 400, "invalid_grant", "Authorization code or PKCE verifier is invalid");
        return;
      }
      if (params.has("resource") && normalizeResource(params.get("resource")!) !== normalizeResource(code.resource ?? `${this.#publicOrigin(request)}/mcp`)) { oauthError(response, 400, "invalid_target", "Resource does not match the authorization grant"); return; }
      if (!this.#tokenRoom(response)) return;
      this.#codes.delete(codeValue);
      this.#issueTokens(response, code.clientId, code.scope, code.resource, randomToken(18), code.clientName);
      return;
    }
    if (params.get("grant_type") === "refresh_token") {
      const refreshValue = params.get("refresh_token") ?? "";
      const refresh = this.#refreshTokens.get(refreshValue);

      if (!refresh || refresh.expiresAt <= Date.now() || refresh.clientId !== params.get("client_id")) {
        oauthError(response, 400, "invalid_grant", "Refresh token is invalid");
        return;
      }
      if (params.has("resource") && normalizeResource(params.get("resource")!) !== normalizeResource(refresh.resource ?? `${this.#publicOrigin(request)}/mcp`)) { oauthError(response, 400, "invalid_target", "Resource does not match the refresh grant"); return; }
      if (params.get("scope") && params.get("scope") !== refresh.scope) { oauthError(response, 400, "invalid_scope", "Refresh cannot expand scope"); return; }
      if (!this.#tokenRoom(response, true)) return;
      this.#refreshTokens.delete(refreshValue);
      this.#issueTokens(response, refresh.clientId, refresh.scope, refresh.resource, refresh.sessionId, refresh.clientName);
      return;
    }
    oauthError(response, 400, "unsupported_grant_type", "Use authorization_code or refresh_token");
  }

  #issueTokens(response: ServerResponse, clientId: string, scope: string, resource: string | undefined, sessionId: string, clientName: string | undefined): void {
    const accessToken = randomToken();
    const refreshToken = randomToken();
    const identity = { clientId, ...(clientName ? { clientName } : {}), sessionId, scope, resource };
    this.#accessTokens.set(accessToken, { ...identity, expiresAt: Date.now() + this.#options.accessTokenTtlSeconds * 1_000 });
    this.#refreshTokens.set(refreshToken, { ...identity, expiresAt: Date.now() + this.#options.refreshTokenTtlSeconds * 1_000 });
    writeJson(response, 200, {
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: this.#options.accessTokenTtlSeconds,
      refresh_token: refreshToken,
      scope,
    });
  }

  async #revoke(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const token = new URLSearchParams(await readBody(request)).get("token") ?? "";
    this.#accessTokens.delete(token);
    this.#refreshTokens.delete(token);
    response.writeHead(200, { "cache-control": "no-store" }).end();
  }
}
