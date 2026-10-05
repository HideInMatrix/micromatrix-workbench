import { Resolver } from "node:dns/promises";
import { request } from "node:https";
import { BlockList, isIP } from "node:net";
function validRedirectUri(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.username || url.password || /[\s\\#]/.test(value) || /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*@/i.test(value)) return false;
    if (url.protocol === "https:") return true;
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  } catch { return false; }
}

export interface CimdClient {
  readonly client_id: string;
  readonly client_name: string;
  readonly redirect_uris: readonly string[];
  readonly token_endpoint_auth_method: "none";
}

const MAX_BYTES = 5 * 1024;
const MAX_CACHE = 100;
const MAX_CONCURRENT = 8;
export class CimdDiscoveryError extends Error {
  constructor(readonly status: 400 | 503, readonly oauthError: "invalid_client_metadata" | "temporarily_unavailable", message: string) {
    super(message);
    this.name = "CimdDiscoveryError";
  }
}
const blocked = new BlockList();
for (const [address, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["192.88.99.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15],
  ["198.51.100.0", 24], ["203.0.113.0", 24], ["224.0.0.0", 3],
] as const) blocked.addSubnet(address, prefix, "ipv4");
const globalV6 = new BlockList();
globalV6.addSubnet("2000::", 3, "ipv6");
for (const [address, prefix] of [["2001::", 23], ["2001:db8::", 32], ["2002::", 16], ["3fff::", 20]] as const) blocked.addSubnet(address, prefix, "ipv6");

/** Conservative global-unicast policy; mapped IPv4, NAT64 and transition ranges are refused. */
export function isPublicMetadataAddress(address: string): boolean {
  const family = isIP(address);
  return family === 4 ? !blocked.check(address, "ipv4")
    : family === 6 && globalV6.check(address, "ipv6") && !blocked.check(address, "ipv6");
}

const fakeIp = new BlockList();
fakeIp.addSubnet("198.18.0.0", 15, "ipv4");
// Fake-IP proxies also publish IPv4-translated AAAA records (RFC 6145).
fakeIp.addSubnet("::ffff:0:c612:0", 111, "ipv6");
export function isFakeMetadataAddress(address: string): boolean {
  const family = isIP(address);
  return family !== 0 && fakeIp.check(address, family === 4 ? "ipv4" : "ipv6");
}

/** Only bootstrap the fixed DNS provider, never the untrusted metadata host. */
async function publicDns(host: string, type: "A" | "AAAA", signal: AbortSignal): Promise<{ address: string; family: number }[]> {
  const url = new URL("https://cloudflare-dns.com/dns-query");
  url.search = new URLSearchParams({ name: host, type }).toString();
  return new Promise((resolve, reject) => {
    const req = request(url, {
      method: "GET", agent: false, signal, maxHeaderSize: 8192,
      headers: { accept: "application/dns-json", "accept-encoding": "identity" },
      lookup: (_host, options, callback) => {
        if (options.all) callback(null, [{ address: "1.1.1.1", family: 4 }]);
        else callback(null, "1.1.1.1", 4);
      },
    }, res => {
      if (res.statusCode !== 200 || String(res.headers["content-type"] ?? "").split(";")[0]!.trim().toLowerCase() !== "application/dns-json"
        || (res.headers["content-encoding"] && res.headers["content-encoding"] !== "identity") || Number(res.headers["content-length"]) > 16 * 1024) {
        reject(new Error("Public DNS response rejected")); res.destroy(); return;
      }
      let size = 0; const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => {
        size += chunk.length;
        if (size > 16 * 1024) { reject(new Error("Public DNS response exceeds limit")); res.destroy(); }
        else chunks.push(chunk);
      });
      res.on("error", reject);
      res.on("aborted", () => reject(new Error("Public DNS response aborted")));
      res.on("end", () => {
        try {
          const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
          const queryType = type === "A" ? 1 : 28;
          const question = data?.Question;
          if (data?.Status !== 0 || data.TC === true || !Array.isArray(question) || question.length !== 1
            || typeof question[0]?.name !== "string" || question[0].name.replace(/\.$/, "").toLowerCase() !== host.toLowerCase()
            || question[0].type !== queryType || (data.Answer !== undefined && (!Array.isArray(data.Answer) || data.Answer.length > 64))) {
            throw new Error("Public DNS question or response is invalid");
          }
          const addresses: { address: string; family: number }[] = [];
          for (const answer of data.Answer ?? []) {
            if (answer?.type !== 1 && answer?.type !== 28) continue; // CNAME, not a connection destination.
            const family = answer.type === 1 ? 4 : 6;
            if (typeof answer.data !== "string" || isIP(answer.data) !== family || !isPublicMetadataAddress(answer.data)) {
              throw new Error("Public DNS returned a nonpublic address");
            }
            addresses.push({ address: answer.data, family });
          }
          resolve(addresses);
        } catch (error) { reject(error); }
      });
    });
    req.on("error", reject); req.end();
  });
}

async function metadataAddresses(host: string, resolver: Resolver, signal: AbortSignal): Promise<{ address: string; family: number }[]> {
  const family = isIP(host);
  let addresses = family ? [{ address: host, family }] : (await Promise.allSettled([
    resolver.resolve4(host), resolver.resolve6(host),
  ])).flatMap((result, index) => result.status === "fulfilled" ? result.value.map(address => ({ address, family: index === 0 ? 4 : 6 })) : []);
  signal.throwIfAborted();
  if (!addresses.length) throw new CimdDiscoveryError(503, "temporarily_unavailable", "CIMD metadata DNS lookup failed; check the desktop application's network/DNS settings");
  if (addresses.every(({ address }) => isPublicMetadataAddress(address))) return addresses;
  // A private/mixed-private DNS answer is still refused, never sent to DoH.
  if (family || !addresses.some(({ address }) => isFakeMetadataAddress(address))
    || addresses.some(({ address }) => !isPublicMetadataAddress(address) && !isFakeMetadataAddress(address))) {
    throw new CimdDiscoveryError(400, "invalid_client_metadata", "CIMD DNS must resolve exclusively to public addresses; private or reserved targets are refused");
  }
  try {
    addresses = (await Promise.all([publicDns(host, "A", signal), publicDns(host, "AAAA", signal)])).flat();
    if (!addresses.length) throw new Error("No public DNS answers");
    return addresses;
  } catch {
    throw new CimdDiscoveryError(503, "temporarily_unavailable", "CIMD DNS returned proxy fake-IP addresses and verified public DNS lookup failed; allow HTTPS to cloudflare-dns.com (1.1.1.1) or exclude the metadata domain from fake-IP DNS");
  }
}

export function metadataUrl(clientId: string): URL {
  const url = new URL(clientId);
  const rawPath = /^https:\/\/[^/?#]+(\/[^?#]*)/i.exec(clientId)?.[1];
  if (clientId.length > 2048 || /[\s\\#?]/.test(clientId) || /^https:\/\/[^/?#]*@/i.test(clientId)
    || !rawPath || /\/(?:\.|%2e){1,2}(?:\/|$)/i.test(rawPath)
    || url.protocol !== "https:" || !url.hostname || url.search
    || url.pathname === "/" || url.username || url.password || url.hash || url.port) {
    throw new Error("CIMD requires a public HTTPS URL with a path, without credentials, fragment or nonstandard port");
  }
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")
    || (isIP(host) && !isPublicMetadataAddress(host))) throw new Error("CIMD metadata must not use a private or reserved address");
  return url;
}

export function parseCimdClient(clientId: string, value: unknown): CimdClient {
  metadataUrl(clientId);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid CIMD document");
  const document = value as Record<string, unknown>;
  const redirects = document.redirect_uris;
  const methods = document.token_endpoint_auth_methods_supported;
  // The plural CIMD field is used by ChatGPT during the MCP transition. Only
  // negotiate explicitly published 'none'; never claim to verify private_key_jwt.
  if (document.client_id !== clientId || typeof document.client_name !== "string"
    || !document.client_name.trim() || document.client_name.length > 128
    || /[\u0000-\u001f\u007f]/.test(document.client_name)
    || !Array.isArray(redirects) || !redirects.length || redirects.length > 32
    || !redirects.every(uri => typeof uri === "string" && uri.length <= 2048 && validRedirectUri(uri))
    || document.client_secret !== undefined || document.client_secret_expires_at !== undefined
    || (typeof document.token_endpoint_auth_method === "string" && document.token_endpoint_auth_method.startsWith("client_secret"))
    || (methods !== undefined && (!Array.isArray(methods) || !methods.every(method => typeof method === "string") || !methods.includes("none")))
    || (methods === undefined && (document.token_endpoint_auth_method ?? "none") !== "none")) {
    throw new Error("CIMD identity, redirect URIs or public-client authentication is invalid");
  }
  if (Array.isArray(methods) && methods.some(method => method.startsWith("client_secret"))) throw new Error("CIMD cannot publish shared-secret authentication");
  if (document.jwks !== undefined) {
    const keys = (document.jwks as { keys?: unknown } | null)?.keys;
    if (!Array.isArray(keys) || keys.some(key => !key || typeof key !== "object"
      || ["d", "p", "q", "dp", "dq", "qi", "oth", "k"].some(field => Object.hasOwn(key, field)))) {
      throw new Error("CIMD must not contain private key material");
    }
  }
  for (const [field, expected, fallback] of [["grant_types", "authorization_code", ["authorization_code"]], ["response_types", "code", ["code"]]] as const) {
    const values = document[field] ?? fallback;
    if (!Array.isArray(values) || !values.every(item => typeof item === "string") || !values.includes(expected)) throw new Error(`Invalid CIMD ${field}`);
  }
  return { client_id: clientId, client_name: document.client_name, redirect_uris: [...redirects], token_endpoint_auth_method: "none" };
}

function cacheLifetime(headers: Readonly<Record<string, string | string[] | undefined>>): number {
  const control = String(headers["cache-control"] ?? "");
  if (/(?:^|,)\s*(?:no-store|no-cache)\b/i.test(control) || headers.vary) return 0;
  const maxAge = /(?:^|,)\s*max-age\s*=\s*"?(\d+)"?/i.exec(control)?.[1];
  const expires = Date.parse(String(headers.expires ?? ""));
  const lifetime = maxAge === undefined ? (Number.isFinite(expires) ? Math.max(0, (expires - Date.now()) / 1000) : 60) : Number(maxAge);
  const rawAge = Number(headers.age ?? 0);
  return Math.max(0, Math.min(300, lifetime - (Number.isFinite(rawAge) ? Math.max(0, rawAge) : lifetime))) * 1000;
}

async function fetchDocument(clientId: string): Promise<{ client: CimdClient; lifetime: number }> {
  const url = metadataUrl(clientId);
  const host = url.hostname.replace(/^\[|\]$/g, "");
  const signal = AbortSignal.timeout(10_000);
  const resolver = new Resolver();
  const cancel = () => resolver.cancel();
  signal.addEventListener("abort", cancel, { once: true });
  try {
    const addresses = await metadataAddresses(host, resolver, signal);
    const pinned = addresses[0]!;
    return await new Promise((resolve, reject) => {
      // Pin the validated address while keeping the original Host/SNI and TLS
      // certificate verification. Never resolve twice, follow redirects, use a
      // proxy environment, send credentials or fetch logo/JWKS URLs. Fake-IP
      // itself is never dialed: any fallback addresses have been revalidated.
      const req = request(url, {
        method: "GET", agent: false, signal, maxHeaderSize: 8192,
        headers: { accept: "application/json", "accept-encoding": "identity" },
        lookup: (_host, options, callback) => {
          if (options.all) callback(null, [{ address: pinned.address, family: pinned.family }]);
          else callback(null, pinned.address, pinned.family);
        },
      }, res => {
        const contentType = String(res.headers["content-type"] ?? "").split(";")[0]!.trim().toLowerCase();
        if (res.statusCode !== 200) {
          const temporary = res.statusCode === 401 || res.statusCode === 403 || res.statusCode === 429 || (res.statusCode ?? 0) >= 500;
          reject(new CimdDiscoveryError(temporary ? 503 : 400, temporary ? "temporarily_unavailable" : "invalid_client_metadata",
            `CIMD metadata HTTPS endpoint returned HTTP ${res.statusCode ?? "unknown"}; redirects are not followed`));
          res.destroy(); return;
        }
        if (!/^application\/(?:json|[a-z0-9.+-]+\+json)$/.test(contentType)
          || (res.headers["content-encoding"] && res.headers["content-encoding"] !== "identity")
          || Number(res.headers["content-length"]) > MAX_BYTES) {
          reject(new Error("CIMD metadata response rejected")); res.destroy(); return;
        }
        let size = 0; const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_BYTES) { reject(new Error("CIMD metadata exceeds 5 KB")); res.destroy(); }
          else chunks.push(chunk);
        });
        res.on("error", () => reject(new CimdDiscoveryError(503, "temporarily_unavailable", "CIMD metadata HTTPS response was interrupted")));
        res.on("aborted", () => reject(new CimdDiscoveryError(503, "temporarily_unavailable", "CIMD metadata HTTPS response was interrupted")));
        res.on("end", () => {
          try { resolve({ client: parseCimdClient(clientId, JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)))), lifetime: cacheLifetime(res.headers) }); }
          catch (error) { reject(error); }
        });
      });
      req.on("error", reject); req.end();
    });
  } catch (error) {
    if (error instanceof CimdDiscoveryError) throw error;
    if (signal.aborted || (error && typeof error === "object" && "code" in error)) {
      throw new CimdDiscoveryError(503, "temporarily_unavailable", "CIMD metadata HTTPS connection failed or timed out; check network connectivity and TLS certificates");
    }
    throw error;
  } finally { signal.removeEventListener("abort", cancel); }
}

/** Bounded in-memory client discovery cache. No disk registry or stale fallback. */
export class CimdClientResolver {
  readonly #cache = new Map<string, { client: CimdClient; expires: number }>();
  readonly #pending = new Map<string, Promise<CimdClient>>();
  #window = 0;
  #requests = 0;
  async resolve(clientId: string): Promise<CimdClient> {
    metadataUrl(clientId);
    const now = Date.now();
    const cached = this.#cache.get(clientId);
    if (cached && cached.expires > now) return cached.client;
    this.#cache.delete(clientId);
    const pending = this.#pending.get(clientId);
    if (pending) return pending;
    if (now - this.#window >= 60_000) { this.#window = now; this.#requests = 0; }
    if (this.#pending.size >= MAX_CONCURRENT || this.#requests >= 60) throw new Error("CIMD discovery limit reached; retry later");
    this.#requests++;
    const promise = fetchDocument(clientId).then(({ client, lifetime }) => {
      if (lifetime > 0) {
        for (const [id, record] of this.#cache) if (record.expires <= Date.now()) this.#cache.delete(id);
        if (this.#cache.size >= MAX_CACHE) this.#cache.delete(this.#cache.keys().next().value!);
        this.#cache.set(clientId, { client, expires: Date.now() + lifetime });
      }
      return client;
    }).finally(() => { this.#pending.delete(clientId); });
    this.#pending.set(clientId, promise);
    return promise;
  }
}
