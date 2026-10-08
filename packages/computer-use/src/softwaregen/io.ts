import { spawn, type ChildProcess } from "node:child_process";
import { constants } from "node:fs";
import { open, realpath } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { ComputerUseError, fail, type Json } from "../protocol.js";
import { safeFilePath, safeHttpPath } from "./audit.js";

export const MAX_BYTES = 1024 * 1024;
export function decodeJson(bytes: Uint8Array): Json {
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as Json; }
  catch { return fail("INVALID_RESPONSE", "Expected UTF-8 JSON; raw response omitted"); }
}
export async function readBoundedFile(file: string): Promise<Buffer> {
  const handle = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size > MAX_BYTES) fail("FILE_LIMIT", "Expected a regular file <= 1 MiB");
    const bytes = Buffer.alloc(MAX_BYTES + 1); let offset = 0;
    while (offset < bytes.length) { const { bytesRead } = await handle.read(bytes, offset, bytes.length - offset, null); if (!bytesRead) break; offset += bytesRead; }
    if (offset > MAX_BYTES) fail("FILE_LIMIT", "File exceeds limit");
    return bytes.subarray(0, offset);
  } finally { await handle.close(); }
}
export function byteSha256(bytes: Uint8Array): string { return createHash("sha256").update(bytes).digest("hex"); }
export async function readScopedJson(root: string, relative: string): Promise<Json> {
  if (!safeFilePath(relative)) fail("OUT_OF_SCOPE", "Invalid document path");
  const file = await realpath(path.resolve(root, relative)), difference = path.relative(root, file);
  if (!difference || difference === ".." || difference.startsWith(`..${path.sep}`) || path.isAbsolute(difference)) fail("OUT_OF_SCOPE", "Document outside approved root");
  return decodeJson(await readBoundedFile(file));
}
export function checkedBaseUrl(value: string): URL {
  let url: URL; try { url = new URL(value); } catch { return fail("INVALID_BINDINGS", "Invalid approved base URL"); }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.username || url.password || url.hash || url.search || !safeHttpPath(url.pathname)
    || url.protocol !== "https:" && !(url.protocol === "http:" && local)) fail("INVALID_BINDINGS", "Require HTTPS or explicit loopback HTTP, without URL credentials/query/fragment");
  return url;
}
function interrupted(signal: AbortSignal): ComputerUseError {
  return new ComputerUseError(signal.reason?.name === "TimeoutError" ? "TRANSPORT_TIMEOUT" : "TRANSPORT_CANCELLED", "Interrupted; mutation outcome may be unknown. Observe before retrying.");
}
/** Private fixed origin; supports ordinary REST, including empty DELETE responses. */
export class HttpJsonChannel {
  readonly #base: URL; readonly #headers: Headers;
  readonly #lifecycle = new AbortController();
  constructor(base: string, headers: Record<string, string>, readonly timeout: number) { this.#base = checkedBaseUrl(base); this.#headers = new Headers(headers); }
  async request(method: string, route: string, query: Record<string, Json>, body: Json | undefined, signal?: AbortSignal): Promise<Json> {
    if (!safeHttpPath(route)) fail("INVALID_ACTION", "Unsafe rendered HTTP route");
    const url = new URL(`${this.#base.href.replace(/\/$/, "")}${route}`);
    if (url.origin !== this.#base.origin) fail("OUT_OF_SCOPE", "Request cannot change approved origin");
    for (const [key, value] of Object.entries(query)) {
      for (const entry of Array.isArray(value) ? value : [value]) {
        if (entry !== null && typeof entry === "object") fail("INVALID_ACTION", "Query parameters must be scalar or arrays of scalars");
        if (entry !== null) url.searchParams.append(key, String(entry));
      }
    }
    const data = body === undefined ? undefined : JSON.stringify(body);
    if (data && Buffer.byteLength(data) > MAX_BYTES) fail("REQUEST_LIMIT", "Request exceeds 1 MiB");
    const combined = AbortSignal.any([this.#lifecycle.signal, AbortSignal.timeout(this.timeout), ...(signal ? [signal] : [])]);
    const headers = new Headers(this.#headers); headers.set("accept", "application/json"); if (data !== undefined) headers.set("content-type", "application/json");
    try {
      combined.throwIfAborted();
      const response = await fetch(url, { method, headers, redirect: "error", signal: combined, ...(data === undefined ? {} : { body: data }) });
      if (!response.ok) {
        await response.body?.cancel();
        throw new ComputerUseError(response.status === 412 || response.status === 409 ? "PRECONDITION_FAILED" : "HTTP_FAILED", `HTTP ${response.status}; response body omitted`);
      }
      if (!response.body) return null;
      const reader = response.body.getReader(), chunks: Uint8Array[] = []; let bytes = 0;
      try {
        for (;;) {
          const chunk = await reader.read(); if (chunk.done) break;
          bytes += chunk.value.length;
          if (bytes > MAX_BYTES) { await reader.cancel(); fail("OUTPUT_LIMIT", "Response exceeds 1 MiB"); }
          chunks.push(chunk.value);
        }
      } finally { reader.releaseLock(); }
      if (!bytes) return null;
      if (!/^application\/(?:[\w.-]+\+)?json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) fail("INVALID_RESPONSE", "Expected JSON Content-Type");
      return decodeJson(Buffer.concat(chunks));
    } catch (error) {
      if (error instanceof ComputerUseError) throw error;
      if (combined.aborted) throw interrupted(combined);
      throw new ComputerUseError("HTTP_FAILED", "Request failed; redirects forbidden and raw network errors omitted");
    }
  }
  close() { this.#lifecycle.abort(); }
}
/** Reviewed argv templates are interpreted before calling this shell=false channel. Not an OS sandbox. */
export class CommandJsonChannel {
  readonly #lifecycle = new AbortController(); readonly #children = new Set<ChildProcess>();
  readonly #treeKills = new Set<Promise<void>>();
  constructor(readonly cwd: string, readonly timeout: number, readonly env: Readonly<Record<string, string>>) {}
  async request(executable: string, argv: string[], stdin: Json | null, signal?: AbortSignal): Promise<Json> {
    if (argv.length > 64 || argv.some(arg => arg.length > 8192 || arg.includes("\0"))) fail("INVALID_ACTION", "Invalid rendered command arguments");
    const input = stdin === null ? undefined : JSON.stringify(stdin);
    if (input && Buffer.byteLength(input) > MAX_BYTES) fail("REQUEST_LIMIT", "Command input exceeds limit");
    const combined = AbortSignal.any([this.#lifecycle.signal, AbortSignal.timeout(this.timeout), ...(signal ? [signal] : [])]);
    if (combined.aborted) throw interrupted(combined);
    if (this.#children.size >= 8) fail("TRANSPORT_BUSY", "Too many active commands");
    return new Promise((resolve, reject) => {
      const child = spawn(executable, argv, { cwd: this.cwd, env: { ...this.env }, windowsHide: true, shell: false,
        detached: process.platform !== "win32", stdio: ["pipe", "pipe", "pipe"] });
      this.#children.add(child);
      const chunks: Buffer[] = []; let bytes = 0, failure: Error | undefined, settled = false;
      let killingWindowsTree = false;
      let killTimer: ReturnType<typeof setTimeout> | undefined, settleTimer: ReturnType<typeof setTimeout> | undefined;
      const kill = (sig: NodeJS.Signals) => {
        if (process.platform !== "win32" && child.pid) { try { process.kill(-child.pid, sig); } catch { child.kill(sig); } }
        else if (child.pid && !killingWindowsTree) {
          killingWindowsTree = true;
          // Capture/kill only this owned PID's tree before terminating its parent.
          const pending = new Promise<void>(resolve => {
            const killer = spawn(path.join(process.env.SYSTEMROOT ?? process.env.SystemRoot ?? "C:\\Windows", "System32", "taskkill.exe"),
              ["/PID", String(child.pid), "/T", "/F"], { shell: false, windowsHide: true, stdio: "ignore" });
            const timer = setTimeout(() => { killer.kill(); child.kill(); resolve(); }, 2000);
            killer.once("error", () => { clearTimeout(timer); child.kill(); resolve(); });
            killer.once("close", () => { clearTimeout(timer); child.kill(); resolve(); });
          });
          this.#treeKills.add(pending); void pending.finally(() => this.#treeKills.delete(pending));
        } else if (!child.pid) child.kill(sig);
      };
      const settle = (error?: Error, result?: Json) => {
        if (settled) return; settled = true; combined.removeEventListener("abort", abort);
        if (killTimer) clearTimeout(killTimer); if (settleTimer) clearTimeout(settleTimer); this.#children.delete(child);
        if (error) reject(error); else resolve(result!);
      };
      const stop = (error: Error) => {
        failure ??= error; kill("SIGTERM");
        killTimer ??= setTimeout(() => kill("SIGKILL"), 250);
        settleTimer ??= setTimeout(() => { child.stdin.destroy(); child.stdout.destroy(); child.stderr.destroy(); settle(failure); }, 1000);
      };
      const abort = () => stop(interrupted(combined));
      combined.addEventListener("abort", abort, { once: true }); if (combined.aborted) abort();
      child.stdout.on("data", (chunk: Buffer) => { bytes += chunk.length; if (bytes > MAX_BYTES) stop(new ComputerUseError("OUTPUT_LIMIT", "Command output exceeds limit")); else chunks.push(chunk); });
      child.stderr.on("data", (chunk: Buffer) => { bytes += chunk.length; if (bytes > MAX_BYTES) stop(new ComputerUseError("OUTPUT_LIMIT", "Command output exceeds limit")); });
      child.stdin.on("error", () => stop(new ComputerUseError("COMMAND_FAILED", "Command input failed; mutation outcome may be unknown")));
      child.on("error", () => { failure ??= new ComputerUseError("COMMAND_FAILED", "Reviewed command could not start; process error omitted"); });
      child.once("close", code => {
        if (failure) return settle(failure);
        if (code !== 0) return settle(new ComputerUseError("COMMAND_FAILED", `Command exited ${code}; output omitted`));
        try { const bytes = Buffer.concat(chunks); settle(undefined, bytes.toString("utf8").trim() ? decodeJson(bytes) : null); }
        catch (error) { settle(error as Error); }
      });
      child.stdin.end(input === undefined ? undefined : `${input}\n`);
    });
  }
  async close() {
    const pending = [...this.#children].map(child => new Promise<void>(resolve => { child.once("close", () => resolve()); setTimeout(resolve, 1100).unref(); }));
    this.#lifecycle.abort(); await Promise.all(pending); await Promise.all([...this.#treeKills]);
  }
}
