import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";

import type { LocalOAuthOptions, McpAuthorization } from "./types.js";

interface ClientRecord {
  readonly client_id: string;
  readonly client_id_issued_at: number;
  readonly client_name?: string;
  readonly redirect_uris: readonly string[];
  readonly grant_types: readonly string[];
  readonly response_types: readonly string[];
  readonly token_endpoint_auth_method: "none";
}

interface AuthorizationCode {
  readonly clientId: string;
  readonly redirectUri: string;
  readonly codeChallenge: string;
  readonly scope: string;
  readonly resource: string | undefined;
  readonly expiresAt: number;
}

interface TokenRecord {
  readonly clientId: string;
  readonly scope: string;
  readonly resource: string | undefined;
  readonly expiresAt: number;
}

const FORM_LIMIT = 64 * 1024;

function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

function sameSecret(actual: string, expected: string): boolean {
  const left = Buffer.from(actual);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

function publicOrigin(request: IncomingMessage): string {
  const forwardedProto = request.headers["x-forwarded-proto"]?.toString().split(",")[0]?.trim();
  const protocol = forwardedProto === "https" ? "https" : "http";
  const forwardedHost = request.headers["x-forwarded-host"]?.toString().split(",")[0]?.trim();
  const host = forwardedHost || request.headers.host || "127.0.0.1";
  return `${protocol}://${host}`;
}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

function oauthError(response: ServerResponse, status: number, error: string, description: string): void {
  writeJson(response, status, { error, error_description: description });
}

async function readBody(request: IncomingMessage): Promise<string> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > FORM_LIMIT) throw new Error("OAuth request body is too large");
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function validRedirectUri(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol === "https:") return true;
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  } catch {
    return false;
  }
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
  readonly #clients = new Map<string, ClientRecord>();
  readonly #codes = new Map<string, AuthorizationCode>();
  readonly #accessTokens = new Map<string, TokenRecord>();
  readonly #refreshTokens = new Map<string, TokenRecord>();

  constructor(options: LocalOAuthOptions) {
    this.#options = {
      ...options,
      accessTokenTtlSeconds: options.accessTokenTtlSeconds ?? 3_600,
      refreshTokenTtlSeconds: options.refreshTokenTtlSeconds ?? 30 * 24 * 3_600,
    };
  }

  get oauthEnabled(): boolean {
    return Boolean(this.#options.password);
  }

  get protectsRequests(): boolean {
    return this.oauthEnabled || Boolean(this.#options.staticBearerToken);
  }

  async authorize(request: IncomingMessage): Promise<boolean> {
    const authorization = request.headers.authorization;
    if (!authorization?.startsWith("Bearer ")) return !this.#options.staticBearerToken && !this.oauthEnabled;
    const token = authorization.slice("Bearer ".length);
    if (this.#options.staticBearerToken && sameSecret(token, this.#options.staticBearerToken)) return true;
    const record = this.#accessTokens.get(token);
    if (!record) return false;
    if (record.expiresAt <= Date.now()) {
      this.#accessTokens.delete(token);
      return false;
    }
    return true;
  }

  challenge(request: IncomingMessage, resourcePath: string): string {
    const metadata = `${publicOrigin(request)}/.well-known/oauth-protected-resource${resourcePath}`;
    return `Bearer resource_metadata="${metadata}", scope="mcp"`;
  }

  async handle(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean> {
    if (!this.oauthEnabled) return false;
    const path = url.pathname;
    if (path === "/.well-known/oauth-protected-resource" || path === "/.well-known/oauth-protected-resource/mcp") {
      this.#metadata(request, response);
      return true;
    }
    if (path === "/.well-known/oauth-authorization-server" || path === "/.well-known/openid-configuration") {
      this.#serverMetadata(request, response);
      return true;
    }
    if (path === "/register" && request.method === "POST") {
      await this.#register(request, response);
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
    const origin = publicOrigin(request);
    writeJson(response, 200, {
      resource: `${origin}/mcp`,
      authorization_servers: [origin],
      scopes_supported: ["mcp"],
      resource_name: "MicroMatrix Pi MCP",
    });
  }

  #serverMetadata(request: IncomingMessage, response: ServerResponse): void {
    const origin = publicOrigin(request);
    writeJson(response, 200, {
      issuer: origin,
      authorization_endpoint: `${origin}/authorize`,
      token_endpoint: `${origin}/token`,
      registration_endpoint: `${origin}/register`,
      revocation_endpoint: `${origin}/revoke`,
      scopes_supported: ["mcp"],
      response_types_supported: ["code"],
      grant_types_supported: ["authorization_code", "refresh_token"],
      code_challenge_methods_supported: ["S256"],
      token_endpoint_auth_methods_supported: ["none"],
    });
  }

  async #register(request: IncomingMessage, response: ServerResponse): Promise<void> {
    let metadata: unknown;
    try { metadata = JSON.parse(await readBody(request)); }
    catch { oauthError(response, 400, "invalid_client_metadata", "Body must be valid JSON"); return; }
    if (!metadata || typeof metadata !== "object") {
      oauthError(response, 400, "invalid_client_metadata", "Client metadata must be an object");
      return;
    }
    const redirectUris = Reflect.get(metadata, "redirect_uris");
    if (!Array.isArray(redirectUris) || redirectUris.length === 0 || !redirectUris.every((item) => typeof item === "string" && validRedirectUri(item))) {
      oauthError(response, 400, "invalid_redirect_uri", "Use HTTPS or a loopback HTTP redirect URI");
      return;
    }
    const clientId = randomToken(24);
    const record: ClientRecord = {
      client_id: clientId,
      client_id_issued_at: Math.floor(Date.now() / 1_000),
      ...(typeof Reflect.get(metadata, "client_name") === "string" ? { client_name: Reflect.get(metadata, "client_name") as string } : {}),
      redirect_uris: redirectUris,
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
      token_endpoint_auth_method: "none",
    };
    this.#clients.set(clientId, record);
    writeJson(response, 201, record);
  }

  async #authorize(request: IncomingMessage, response: ServerResponse, url: URL): Promise<void> {
    const params = new URLSearchParams(url.search);
    if (request.method === "POST") {
      for (const [key, value] of new URLSearchParams(await readBody(request))) params.set(key, value);
    }
    const clientId = params.get("client_id") ?? "";
    const redirectUri = params.get("redirect_uri") ?? "";
    const state = params.get("state") ?? undefined;
    const client = this.#clients.get(clientId);
    if (!client || !client.redirect_uris.includes(redirectUri)) {
      oauthError(response, 400, "invalid_request", "Unknown client or redirect URI");
      return;
    }
    const challenge = params.get("code_challenge") ?? "";
    if (params.get("response_type") !== "code" || params.get("code_challenge_method") !== "S256" || !challenge) {
      response.writeHead(302, { location: redirectWith(redirectUri, { error: "invalid_request", state }) }).end();
      return;
    }
    if (request.method === "GET") {
      const action = escapeHtml(`${url.pathname}${url.search}`);
      const clientName = escapeHtml(client.client_name ?? client.client_id);
      response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
      response.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>授权 MCP</title><style>body{font:14px system-ui;background:#111827;color:#f9fafb;display:grid;place-items:center;min-height:100vh;margin:0}.card{width:min(420px,calc(100% - 40px));padding:24px;border:1px solid #374151;border-radius:12px;background:#1f2937}input,button{box-sizing:border-box;width:100%;padding:11px;border-radius:8px;border:1px solid #4b5563;margin-top:12px}button{background:#2563eb;color:#fff;font-weight:600}</style><form class="card" method="post" action="${action}"><h1>授权 MCP 客户端</h1><p>${clientName} 请求访问本机 Pi 工具。</p><input type="password" name="password" autocomplete="current-password" placeholder="OAuth 密码" required><button type="submit">授权连接</button></form></html>`);
      return;
    }
    const expected = this.#options.password ?? "";
    if (!sameSecret(params.get("password") ?? "", expected)) {
      response.writeHead(302, { location: redirectWith(redirectUri, { error: "access_denied", error_description: "Invalid password", state }) }).end();
      return;
    }
    const code = randomToken();
    this.#codes.set(code, {
      clientId,
      redirectUri,
      codeChallenge: challenge,
      scope: params.get("scope") || "mcp",
      resource: params.get("resource") ?? undefined,
      expiresAt: Date.now() + 5 * 60_000,
    });
    response.writeHead(302, { location: redirectWith(redirectUri, { code, state }) }).end();
  }

  async #token(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const params = new URLSearchParams(await readBody(request));
    if (params.get("grant_type") === "authorization_code") {
      const codeValue = params.get("code") ?? "";
      const code = this.#codes.get(codeValue);
      this.#codes.delete(codeValue);
      const verifier = params.get("code_verifier") ?? "";
      const computed = createHash("sha256").update(verifier).digest("base64url");
      if (!code || code.expiresAt <= Date.now() || code.clientId !== params.get("client_id") || code.redirectUri !== params.get("redirect_uri") || !sameSecret(computed, code.codeChallenge)) {
        oauthError(response, 400, "invalid_grant", "Authorization code or PKCE verifier is invalid");
        return;
      }
      this.#issueTokens(response, code.clientId, code.scope, code.resource);
      return;
    }
    if (params.get("grant_type") === "refresh_token") {
      const refreshValue = params.get("refresh_token") ?? "";
      const refresh = this.#refreshTokens.get(refreshValue);
      this.#refreshTokens.delete(refreshValue);
      if (!refresh || refresh.expiresAt <= Date.now() || refresh.clientId !== params.get("client_id")) {
        oauthError(response, 400, "invalid_grant", "Refresh token is invalid");
        return;
      }
      this.#issueTokens(response, refresh.clientId, params.get("scope") || refresh.scope, refresh.resource);
      return;
    }
    oauthError(response, 400, "unsupported_grant_type", "Use authorization_code or refresh_token");
  }

  #issueTokens(response: ServerResponse, clientId: string, scope: string, resource: string | undefined): void {
    const accessToken = randomToken();
    const refreshToken = randomToken();
    this.#accessTokens.set(accessToken, { clientId, scope, resource, expiresAt: Date.now() + this.#options.accessTokenTtlSeconds * 1_000 });
    this.#refreshTokens.set(refreshToken, { clientId, scope, resource, expiresAt: Date.now() + this.#options.refreshTokenTtlSeconds * 1_000 });
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
