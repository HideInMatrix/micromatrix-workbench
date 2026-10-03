import { randomBytes } from "node:crypto";
import { closeSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export interface ClientRecord {
  readonly client_id: string;
  readonly client_id_issued_at: number;
  readonly client_name?: string;
  readonly redirect_uris: readonly string[];
  readonly grant_types: readonly string[];
  readonly response_types: readonly string[];
  readonly token_endpoint_auth_method: "none";
}

const MAX_CLIENTS = 1_000;
const MAX_BYTES = 4 * 1024 * 1024;

export function validRedirectUri(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol === "https:") return true;
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  } catch { return false; }
}

function clientRecord(value: unknown): ClientRecord {
  if (!value || typeof value !== "object") throw new Error("Invalid OAuth client record");
  const id = Reflect.get(value, "client_id");
  const issued = Reflect.get(value, "client_id_issued_at");
  const name = Reflect.get(value, "client_name");
  const redirects = Reflect.get(value, "redirect_uris");
  const grants = Reflect.get(value, "grant_types");
  const responses = Reflect.get(value, "response_types");
  if (typeof id !== "string" || !/^[A-Za-z0-9_-]{32}$/.test(id)
    || !Number.isSafeInteger(issued) || issued < 0
    || (name !== undefined && typeof name !== "string")
    || !Array.isArray(redirects) || !redirects.length
    || !redirects.every((uri: unknown) => typeof uri === "string" && validRedirectUri(uri))
    || !Array.isArray(grants) || grants.length !== 2
    || grants[0] !== "authorization_code" || grants[1] !== "refresh_token"
    || !Array.isArray(responses) || responses.length !== 1 || responses[0] !== "code"
    || Reflect.get(value, "token_endpoint_auth_method") !== "none") {
    throw new Error("Invalid OAuth client record");
  }
  // Whitelist public registration fields; never serialize authorization grants or credentials.
  return {
    client_id: id, client_id_issued_at: issued,
    ...(name === undefined ? {} : { client_name: name }),
    redirect_uris: redirects, grant_types: grants, response_types: responses,
    token_endpoint_auth_method: "none",
  };
}

export function loadClients(path: string): readonly ClientRecord[] {
  let bytes: Buffer;
  try {
    const info = lstatSync(path);
    if (!info.isFile() || info.size > MAX_BYTES) throw new Error("Invalid OAuth client store file");
    bytes = readFileSync(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  if (bytes.length > MAX_BYTES) throw new Error("OAuth client store limit reached");
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!value || typeof value !== "object" || Reflect.get(value, "version") !== 1) {
    throw new Error("Invalid OAuth client store version");
  }
  const records = Reflect.get(value, "clients");
  if (!Array.isArray(records) || records.length > MAX_CLIENTS) throw new Error("Invalid OAuth client store records");
  const clients = records.map(clientRecord);
  if (new Set(clients.map((client) => client.client_id)).size !== clients.length) throw new Error("Duplicate OAuth client registration");
  return clients;
}

export function saveClients(path: string, clients: readonly ClientRecord[]): void {
  if (clients.length > MAX_CLIENTS) throw new Error("OAuth client registration limit reached");
  const bytes = `${JSON.stringify({ version: 1, clients: clients.map(clientRecord) })}\n`;
  if (Buffer.byteLength(bytes) > MAX_BYTES) throw new Error("OAuth client store limit reached");
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`;
  let fd: number | undefined;
  try {
    fd = openSync(temporary, "wx", 0o600);
    writeFileSync(fd, bytes, "utf8");
    fsyncSync(fd);
    closeSync(fd); fd = undefined;
    renameSync(temporary, path);
  } finally {
    if (fd !== undefined) closeSync(fd);
    try { unlinkSync(temporary); } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
}
