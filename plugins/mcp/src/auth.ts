import { createHash, randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, statSync, writeFileSync, renameSync, rmSync } from "node:fs";
import { dirname } from "node:path";
import { createServer, type Server } from "node:http";
import { auth, type OAuthClientProvider, type OAuthDiscoveryState } from "@modelcontextprotocol/sdk/client/auth.js";
import { OAuthClientInformationSchema, OAuthTokensSchema, type OAuthClientInformationMixed, type OAuthTokens } from "@modelcontextprotocol/sdk/shared/auth.js";
import { parseMcpConnection, type McpConnectionConfig } from "@micromatrix/plugin-kit";

interface Credentials { values: Record<string, string>; oauth?: { client?: OAuthClientInformationMixed; tokens?: OAuthTokens; redirect: string; discovery?: OAuthDiscoveryState } }
interface Login { previous?: Credentials["oauth"]; key: string; identity: string; server: Server; timer: ReturnType<typeof setTimeout>; state: string; status: "pending" | "authorized" | "failed" | "cancelled"; message: string }
function key(config: McpConnectionConfig): string {
  return createHash("sha256").update(JSON.stringify([config.id, config.transport, config.url, config.command, config.args])).digest("hex");
}
function identityKey(config: McpConnectionConfig): string { return JSON.stringify([config.auth, config.clientMetadataUrl, config.oauthRedirectUri]); }
function matchesIdentity(config: McpConnectionConfig, oauth: Credentials["oauth"]): boolean {
  return config.auth === "oauth" && Boolean(config.clientMetadataUrl) && oauth?.client?.client_id === config.clientMetadataUrl && oauth?.redirect === config.oauthRedirectUri;
}
function cimdConfiguration(config: McpConnectionConfig): { clientId: string; redirect: URL } {
  const parsed = parseMcpConnection(config);
  if (parsed.transport !== "http" || parsed.auth !== "oauth" || !parsed.clientMetadataUrl || !parsed.oauthRedirectUri) {
    throw new Error("CIMD-only OAuth requires your hosted client metadata URL and the exact fixed loopback callback; edit this MCP connection");
  }
  return { clientId: parsed.clientMetadataUrl, redirect: new URL(parsed.oauthRedirectUri) };
}
function validateDiscovery(discovery: OAuthDiscoveryState): void {
  const metadata = discovery.authorizationServerMetadata;
  if (metadata?.client_id_metadata_document_supported !== true || !metadata.code_challenge_methods_supported?.includes("S256")
    || !metadata.token_endpoint_auth_methods_supported?.includes("none")) {
    throw new Error("External authorization server must support CIMD, S256 PKCE and public-client auth (none); DCR fallback is disabled");
  }
}
function safeUrl(value: string | URL): URL {
  const url = new URL(value);
  if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)))) throw new Error("OAuth requires HTTPS or loopback HTTP");
  return url;
}
function boundIssuer(value: unknown): value is string {
  if (typeof value !== "string" || !value) return false;
  try { const url=safeUrl(value); return !url.search && !url.hash; } catch { return false; }
}
function sameIssuer(a: string, b: string): boolean {
  // Match the SDK's parsed-URL/trailing-slash comparison, not just the host.
  const x=safeUrl(a).href, y=safeUrl(b).href;
  return x===y || x.replace(/\/$/,"")===y.replace(/\/$/,"");
}
/** Local-only credential store. Never included in snapshots or the public MCP. */
export class McpAuthStore {
  #records: Record<string, Credentials> = {};
  #logins = new Map<string, Login>();
  #disposed = false;
  constructor(readonly path: string, private remember: boolean) {
    if (remember) {
      let migratedOAuth = false;
      try {
        if (statSync(path).size > 2_000_000) throw new Error("Credential file too large");
        const value: unknown = JSON.parse(readFileSync(path, "utf8"));
        if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length > 32) throw new Error("Invalid credential store");
        for (const [id, item] of Object.entries(value)) {
          if (!/^[a-f0-9]{64}$/.test(id) || !item || typeof item !== "object" || Array.isArray(item)) throw new Error("Invalid credential record");
          const record = item as Credentials;
          if (!record.values || typeof record.values !== "object" || Array.isArray(record.values) || Object.keys(record.values).length > 100) throw new Error("Invalid credential values");
          for (const [name, secret] of Object.entries(record.values)) if (!/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) || typeof secret !== "string" || !secret || secret.length > 16384 || secret.includes("\0")) throw new Error("Invalid credential value");
          if (record.oauth) {
            safeUrl(record.oauth.redirect);
            const tokens = record.oauth.tokens ? OAuthTokensSchema.parse(record.oauth.tokens) : undefined;
            if (record.oauth.client) {
              const client = OAuthClientInformationSchema.parse(record.oauth.client);
              // Do not bind legacy credentials to whatever issuer a remote MCP
              // advertises on first use. Re-login once; keep header secrets.
              if (!/^https:\/\//i.test(client.client_id) || client.client_secret || !boundIssuer(client.issuer)
                || (tokens && (!boundIssuer(tokens.issuer) || !sameIssuer(client.issuer,tokens.issuer)))) { delete record.oauth; migratedOAuth = true; }
              else { record.oauth.client = {...record.oauth.client, ...client}; if (tokens) record.oauth.tokens = {...record.oauth.tokens, ...tokens}; }
            }
            else { delete record.oauth; migratedOAuth = true; }
            // Re-discover on startup, rather than trusting persisted endpoint metadata.
            if (record.oauth) delete record.oauth.discovery;
          }
          this.#records[id] = record;
        }
        if (migratedOAuth) this.#persist();
      }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw new Error("Cannot load local MCP credentials"); }
    } else rmSync(path, { force: true });
  }
  #record(config: McpConnectionConfig): Credentials {
    const id = key(config);
    if (!this.#records[id] && Object.keys(this.#records).length >= 32) throw new Error("Too many MCP credential records");
    return this.#records[id] ??= { values: {} };
  }
  values(config: McpConnectionConfig): Readonly<Record<string, string>> { return this.#records[key(config)]?.values ?? {}; }
  summary(config: McpConnectionConfig) {
    const record = this.#records[key(config)]; const login = this.#logins.get(config.id);
    const matching = login?.key === key(config) && login.identity === identityKey(config);
    return { keys: Object.keys(record?.values ?? {}), oauth: matching ? login.status : matchesIdentity(config, record?.oauth) && record?.oauth?.tokens ? "authorized" : "logged_out",
      message: matching ? login.message : "" };
  }
  update(config: McpConnectionConfig, updates: unknown): void {
    if (!updates || typeof updates !== "object" || Array.isArray(updates)) throw new Error("Credentials must be an object");
    const entries = Object.entries(updates);
    if (entries.length > 100) throw new Error("Too many credential variables");
    const record = this.#record(config); const values = Object.fromEntries(Object.entries(record.values));
    for (const [name, value] of entries) {
      if (!/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) || (value !== null && (typeof value !== "string" || !value || value.length > 16384 || value.includes("\0")))) throw new Error("Invalid credential variable or value");
      if (value === null) delete values[name]; else Object.defineProperty(values, name, { value, enumerable: true, configurable: true, writable: true });
    }
    this.#replace(config, { ...record, values });
  }
  setRemember(value: boolean): void { const previous = this.remember; this.remember = value; try { this.#persist(); } catch (error) { this.remember = previous; throw error; } }
  #persist(): void {
    const document = JSON.stringify(this.#records);
    if (Buffer.byteLength(document) > 2_000_000) throw new Error("MCP credential store exceeds 2 MB");
    if (!this.remember) { rmSync(this.path, { force: true }); return; }
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${process.pid}.tmp`;
    try { writeFileSync(temporary, document, { mode: 0o600 }); renameSync(temporary, this.path); }
    finally { rmSync(temporary, { force: true }); }
  }
  #replace(config: McpConnectionConfig, record: Credentials): void {
    const id = key(config), previous = this.#records[id];
    if (!previous && Object.keys(this.#records).length >= 32) throw new Error("Too many MCP credential records");
    this.#records[id] = record;
    try { this.#persist(); } catch (error) { if (previous) this.#records[id] = previous; else delete this.#records[id]; throw error; }
  }
  prune(configs: readonly McpConnectionConfig[]): void {
    for (const [id, login] of this.#logins) if (!configs.some(config => key(config) === login.key && config.id === id && identityKey(config) === login.identity)) {
      this.cancel(id); this.#logins.delete(id);
    }
    const keep = new Set(configs.map(key)); const previous = this.#records;
    this.#records = Object.fromEntries(Object.entries(previous).filter(([id]) => keep.has(id)));
    for (const config of configs) {
      const id = key(config), record = this.#records[id];
      if (record?.oauth && !matchesIdentity(config, record.oauth)) this.#records[id] = { values: record.values };
    }
    try { this.#persist(); } catch (error) { this.#records = previous; throw error; }
  }
  provider(config: McpConnectionConfig, interactive?: { redirect: string; state: string; redirectTo: (url: URL) => void }): OAuthClientProvider {
    const identity = cimdConfiguration(config);
    let verifier = "";
    const record = () => this.#records[key(config)] ?? { values: {} };
    const get = () => matchesIdentity(config, record().oauth) ? record().oauth : undefined;
    const assertActive = () => {
      if (this.#disposed || (interactive && (this.#logins.get(config.id)?.state !== interactive.state || this.#logins.get(config.id)?.status !== "pending"))) throw new Error("OAuth attempt cancelled");
    };
    const update = (part: Partial<NonNullable<Credentials["oauth"]>>) => {
      assertActive();
      this.#replace(config, { ...record(), oauth: { redirect: interactive?.redirect ?? get()?.redirect ?? "", ...get(), ...part } });
    };
    return {
      get redirectUrl() { return identity.redirect.href; },
      clientMetadataUrl: identity.clientId,
      get clientMetadata() { return { client_name: "micromatrix agent", redirect_uris: [String(this.redirectUrl)], grant_types: ["authorization_code", "refresh_token"], response_types: ["code"], token_endpoint_auth_method: "none" }; },
      state: () => interactive?.state ?? "",
      clientInformation: () => {
        if (!interactive && (!get()?.tokens || get()?.client?.client_id !== identity.clientId)) throw new Error(`MCP ${config.id} requires CIMD OAuth login; use the extension Login button`);
        // Always return URL-based identity: the SDK's registration branch is
        // unreachable, including invalid_client retries. Discovery is checked
        // separately, so a DCR-only provider cannot silently accept this ID.
        const client=get()?.client;
        if (!interactive && (!boundIssuer(client?.issuer) || !boundIssuer(get()?.tokens?.issuer))) throw new Error(`MCP ${config.id} requires issuer-bound OAuth login; use the extension Login button`);
        return { ...client, client_id: identity.clientId, token_endpoint_auth_method: "none" };
      },
      saveClientInformation: client => {
        if (client.client_id !== identity.clientId || client.client_secret || !boundIssuer(client.issuer)) throw new Error("CIMD credentials require the configured public client ID and issuer binding");
        const previous=get()?.client?.issuer;
        if (!interactive && (!boundIssuer(previous) || !sameIssuer(previous,client.issuer))) throw new Error(`MCP ${config.id} authorization server changed; use the extension Login button`);
        update({ client: {...client, token_endpoint_auth_method: "none"} });
      },
      tokens: () => get()?.tokens,
      saveTokens: tokens => {
        const clientIssuer=get()?.client?.issuer;
        if (!boundIssuer(tokens.issuer) || !boundIssuer(clientIssuer) || !sameIssuer(clientIssuer,tokens.issuer)) throw new Error("OAuth tokens must retain the SDK's matching issuer binding");
        update({ tokens: {...tokens} });
      },
      redirectToAuthorization: url => {
        safeUrl(url);
        if (!interactive) throw new Error(`MCP ${config.id} requires OAuth login; use the extension Login button`);
        interactive.redirectTo(url);
      },
      saveCodeVerifier: value => { verifier = value; },
      codeVerifier: () => { if (!verifier) throw new Error("OAuth PKCE verifier missing"); return verifier; },
      saveDiscoveryState: discovery => { validateDiscovery(discovery); update({ discovery }); },
      discoveryState: () => { const state = get()?.discovery; if (state) validateDiscovery(state); return state; },
      invalidateCredentials: scope => {
        assertActive();
        const oauth = { ...get(), redirect: get()?.redirect ?? "" };
        if (scope === "all" || scope === "client") delete oauth.client;
        if (scope === "all" || scope === "tokens") delete oauth.tokens;
        if (scope === "all" || scope === "discovery") delete oauth.discovery;
        if (scope === "all" || scope === "verifier") verifier = "";
        if (!this.#disposed) this.#replace(config, { ...record(), oauth });
      },
    };
  }
  readonly fetchOAuth: typeof fetch = async (input, init) => {
    safeUrl(input instanceof Request ? input.url : input);
    const timeout = AbortSignal.timeout(15_000);
    return fetch(input, { ...init, redirect: "error", signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout });
  };
  readonly fetchMcp: typeof fetch = async (input, init) => {
    safeUrl(input instanceof Request ? input.url : input);
    if (init?.method === "GET") {
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15_000);
      try { return await fetch(input, { ...init, redirect: "error", signal: init.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal }); }
      finally { clearTimeout(timer); } // GET is a long-lived notification stream, not a 15s body.
    }
    const timeout = AbortSignal.timeout(60_000);
    return fetch(input, { ...init, redirect: "error", signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout });
  };
  cancelPending(): void { for (const [id, login] of this.#logins) if (login.status === "pending") this.cancel(id); }
  async begin(config: McpConnectionConfig): Promise<{ url: string }> {
    const identity = cimdConfiguration(config);
    this.cancel(config.id);
    const state = randomBytes(32).toString("base64url");
    let provider: OAuthClientProvider;
    let exchanging = false;
    let expectedIssuer: string | undefined;
    const server = createServer((request, response) => {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      response.setHeader("cache-control", "no-store");
      response.setHeader("content-type", "text/plain; charset=utf-8");
      response.setHeader("content-security-policy", "default-src 'none'; frame-ancestors 'none'");
      if (request.method !== "GET" || url.pathname !== identity.redirect.pathname || url.searchParams.getAll("state").length !== 1 || url.searchParams.get("state") !== state || exchanging) { response.writeHead(400).end("Invalid OAuth callback"); return; }
      const login = this.#logins.get(config.id)!;
      if (url.searchParams.has("error") || url.searchParams.getAll("code").length !== 1 || !url.searchParams.get("code")
        || (expectedIssuer && (url.searchParams.getAll("iss").length !== 1 || url.searchParams.get("iss") !== expectedIssuer))) {
        this.cancel(config.id, false); login.status = "failed"; login.message = "Authorization denied, missing code or incorrect issuer";
        response.writeHead(400).end(login.message); clearTimeout(login.timer); server.close(); return;
      }
      exchanging = true;
      void auth(provider, { serverUrl: config.url, authorizationCode: url.searchParams.get("code")!, fetchFn: this.fetchOAuth }).then(result => {
        if (result !== "AUTHORIZED") throw new Error("OAuth exchange incomplete");
        login.status = "authorized"; login.message = ""; delete login.previous; response.end("授权完成，可以关闭此页面并返回 micromatrix agent。");
      }).catch(() => { this.cancel(config.id, false); login.status = "failed"; login.message = "OAuth token exchange failed; retry login"; response.writeHead(400).end(login.message); })
        .finally(() => { clearTimeout(login.timer); server.close(); });
    });
    server.requestTimeout = 15_000; server.headersTimeout = 15_000; server.maxConnections = 8;
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(Number(identity.redirect.port), "127.0.0.1", () => { server.off("error", reject); resolve(); }); });
    const address = server.address(); if (!address || typeof address === "string") throw new Error("OAuth callback listener unavailable");
    const redirect = identity.redirect.href;
    const previous = matchesIdentity(config, this.#record(config).oauth) ? this.#record(config).oauth : undefined;
    const login: Login = { ...(previous ? { previous } : {}), key: key(config), identity: identityKey(config), state, server, status: "pending", message: "", timer: setTimeout(() => this.cancel(config.id), 180_000) };
    login.timer.unref(); this.#logins.set(config.id, login);
    // Reauthorize the same URL identity. Keep old successful credentials until
    // login succeeds, so closing a browser doesn't log out.
    let authorizationUrl = "";
    try {
      this.#replace(config, { ...this.#record(config), oauth: { redirect, client: { client_id: identity.clientId, token_endpoint_auth_method: "none" } } });
      provider = this.provider(config, { redirect, state, redirectTo: url => { authorizationUrl = url.href; } });
      const result = await auth(provider, { serverUrl: config.url, fetchFn: this.fetchOAuth });
      if (result !== "REDIRECT" || !authorizationUrl) throw new Error("OAuth login did not return an authorization URL");
      const discovery = await provider.discoveryState?.();
      if (discovery?.authorizationServerMetadata && Reflect.get(discovery.authorizationServerMetadata, "authorization_response_iss_parameter_supported") === true) {
        const issuer = discovery.authorizationServerMetadata.issuer;
        if (typeof issuer !== "string" || !issuer) throw new Error("OAuth discovery lacks issuer");
        expectedIssuer = issuer;
      }
      return { url: authorizationUrl };
    } catch (error) {
      this.cancel(config.id);
      throw new Error(`CIMD OAuth discovery failed for ${config.id}; server must advertise CIMD, S256 PKCE and auth method none`);
    }
  }
  cancel(id: string, disconnect = true): void {
    const login = this.#logins.get(id); if (!login) return;
    clearTimeout(login.timer); login.server.close(); if (disconnect) login.server.closeAllConnections();
    if (login.status === "pending") {
      const record = this.#records[login.key];
      if (record) {
        const candidate = { values: record.values, ...(login.previous ? { oauth: login.previous } : {}) };
        this.#records[login.key] = candidate;
        try { this.#persist(); }
        catch { login.status = "failed"; login.message = "OAuth cancelled; could not persist restored credentials"; delete login.previous; return; }
      }
      delete login.previous;
      login.status = "cancelled"; login.message = "Authorization cancelled or timed out";
    }
  }
  logout(config: McpConnectionConfig): void { this.cancel(config.id); this.#logins.delete(config.id); this.#replace(config, { values: this.#record(config).values }); }
  close(): void { this.#disposed = true; for (const id of this.#logins.keys()) this.cancel(id); this.#logins.clear(); }
}
