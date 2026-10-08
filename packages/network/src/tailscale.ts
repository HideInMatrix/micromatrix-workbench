import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { assertExecutable } from "./process.js";
import { NetworkHealthMonitor } from "./health.js";
import { providerResult, type NetworkProvider, type NetworkProviderContext, type NetworkProviderResult, type TailscaleProviderOptions } from "./types.js";

const execFileAsync = promisify(execFile);
function object(value: unknown): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Tailscale status JSON");
  return value as Record<string, any>;
}
function canonical(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) return JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, JSON.parse(canonical(v))])));
  return JSON.stringify(value ?? null);
}
export class TailscaleNetworkProvider implements NetworkProvider {
  readonly key = "tailscale";
  readonly #options: TailscaleProviderOptions;
  readonly #port: string;
  readonly #hostPort: string;
  #target: string | undefined;
  #owned: string | undefined;
  #monitor: NetworkHealthMonitor | undefined;
  #candidate = false;
  #starting: Promise<NetworkProviderResult> | undefined;
  #startingAbort: AbortController | undefined;
  #stopping: Promise<void> | undefined;
  constructor(options: TailscaleProviderOptions, private readonly command?: (args: string[], signal?: AbortSignal) => Promise<string>) {
    if (!options.publicUrl) throw new Error("Tailscale Funnel requires its HTTPS public URL");
    const url = new URL(options.publicUrl);
    this.#port = url.port || "443"; this.#hostPort = `${url.hostname}:${this.#port}`;
    if (url.protocol !== "https:" || !url.hostname.endsWith(".ts.net") || !["443", "8443", "10000"].includes(this.#port) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("Tailscale Funnel requires a ts.net HTTPS origin on port 443, 8443 or 10000");
    this.#options = options;
  }
  async preflight(): Promise<void> { await assertExecutable(this.#options.executable); }
  async #run(args: string[], signal?: AbortSignal): Promise<string> {
    if (this.command) return this.command(args, signal); // trusted-host/test injection, never a serialized configuration field
    const { stdout } = await execFileAsync(this.#options.executable, args, { timeout: args.includes("status") ? 2000 : 3000, maxBuffer: 262144, windowsHide: true, ...(signal ? { signal } : {}) });
    return stdout;
  }
  async #status(signal?: AbortSignal): Promise<Record<string, any>> {
    return object(JSON.parse(await this.#run(["funnel", "status", "--json"], signal)));
  }
  #portOccupied(status: Record<string, any>): boolean {
    if (status.TCP?.[this.#port] || Object.keys(status.Web ?? {}).some(key => key.endsWith(`:${this.#port}`)) || Object.keys(status.AllowFunnel ?? {}).some(key => key.endsWith(`:${this.#port}`))) return true;
    return Object.values(status.Foreground ?? {}).some(value => this.#portOccupied(object(value)));
  }
  #footprint(status: Record<string, any>): string | undefined {
    if (!status.TCP?.[this.#port]?.HTTPS || status.AllowFunnel?.[this.#hostPort] !== true) return undefined;
    const web = status.Web?.[this.#hostPort];
    if (!web || Object.keys(web.Handlers ?? {}).length !== 1 || web.Handlers["/"]?.Proxy !== this.#target) return undefined;
    if (Object.keys(status.AllowFunnel ?? {}).some(key => key !== this.#hostPort && key.endsWith(`:${this.#port}`)) || Object.keys(status.Web ?? {}).some(key => key !== this.#hostPort && key.endsWith(`:${this.#port}`)) || Object.values(status.Foreground ?? {}).some(value => this.#portOccupied(object(value)))) return undefined;
    return canonical({ tcp: status.TCP[this.#port], web, funnel: true });
  }
  start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    if (this.#candidate || this.#starting || this.#stopping) return Promise.reject(new Error("Tailscale Funnel already started or changing state"));
    const abort = new AbortController(); this.#startingAbort = abort;
    const signal = context.signal ? AbortSignal.any([context.signal, abort.signal]) : abort.signal;
    const work = this.#start(context, signal); this.#starting = work;
    void work.finally(() => { if (this.#starting === work) { this.#starting = undefined; this.#startingAbort = undefined; } }).catch(() => {});
    return work;
  }
  async #start(context: NetworkProviderContext, signal: AbortSignal): Promise<NetworkProviderResult> {
    signal.throwIfAborted();
    const before = await this.#status(signal);
    signal.throwIfAborted();
    if (this.#portOccupied(before)) throw new Error(`Tailscale port ${this.#port} already has user-owned Serve/Funnel configuration; refusing to overwrite it`);
    this.#target = context.localBaseUrl; this.#candidate = true;
    await this.#run(["funnel", `--https=${this.#port}`, "--bg", "--yes", context.localBaseUrl], signal);
    signal.throwIfAborted();
    this.#owned = this.#footprint(await this.#status(signal));
    signal.throwIfAborted();
    if (!this.#owned) throw new Error("Tailscale status does not confirm this instance's exact Funnel route");
    this.#monitor = new NetworkHealthMonitor(async signal => {
      if (this.#footprint(await this.#status(signal)) !== this.#owned) throw new Error("Tailscale owned route changed or disappeared");
    }, context.onUnexpectedExit);
    this.#monitor.start();
    context.logger.log("info", "Owned Tailscale Funnel configured");
    return providerResult(this.key, this.#options.publicUrl, "Tailscale Funnel");
  }
  stop(): Promise<void> {
    if (this.#stopping) return this.#stopping;
    this.#startingAbort?.abort();
    const work = this.#stop(); this.#stopping = work;
    void work.finally(() => { if (this.#stopping === work) this.#stopping = undefined; }).catch(() => {});
    return work;
  }
  async #stop(): Promise<void> {
    // Drain/abort the CLI before checking ownership: otherwise Stop could
    // clear the candidate while an in-flight command later creates a Funnel.
    await this.#starting?.catch(() => {});
    await this.#monitor?.stop(); this.#monitor = undefined;
    if (!this.#candidate) return;
    const status = await this.#status(), footprint = this.#footprint(status);
    if (!footprint && !this.#portOccupied(status)) { this.#candidate = false; this.#owned = undefined; this.#target = undefined; return; }
    if (!footprint || this.#owned && footprint !== this.#owned) {
      this.#candidate = false;
      throw new Error("Tailscale route changed externally; leaving user configuration untouched");
    }
    await this.#run(["funnel", `--https=${this.#port}`, "off"]);
    this.#candidate = false; this.#owned = undefined; this.#target = undefined;
  }
}
