import { setTimeout as delay } from "node:timers/promises";

export class PublicRouteError extends Error {
  constructor(readonly code: string, message: string) { super(message); this.name = "PublicRouteError"; }
}

/** An owned service nonce, not just HTTP 200 or a printed URL. No credentials
 * are sent. Redirects and unbounded bodies are refused. */
export async function probePublicService(base: string, instanceId: string, signal?: AbortSignal): Promise<void> {
  try {
    const abort = AbortSignal.timeout(3000);
    const response = await fetch(`${base}/healthz`, { redirect: "error", headers: { "ngrok-skip-browser-warning": "1" },
      signal: signal ? AbortSignal.any([signal, abort]) : abort });
    if (!response.ok) { await response.body?.cancel(); throw new PublicRouteError("http_error", `Public health returned HTTP ${response.status}`); }
    if (!response.headers.get("content-type")?.includes("application/json")) { await response.body?.cancel(); throw new PublicRouteError("unexpected_content_type", "Public route did not return service health JSON"); }
    let size = 0; const chunks: Uint8Array[] = [];
    if (response.body) for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 16384) throw new PublicRouteError("response_too_large", "Public health response exceeded limit");
      chunks.push(chunk);
    }
    let health: unknown;
    try { health = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch { throw new PublicRouteError("invalid_json", "Public health returned invalid JSON"); }
    if (!health || typeof health !== "object" || Reflect.get(health, "ok") !== true || Reflect.get(health, "instance_id") !== instanceId) throw new PublicRouteError("instance_mismatch", "Public route reaches a different service instance");
  } catch (error) {
    if (signal?.aborted) throw signal.reason;
    if (error instanceof PublicRouteError) throw error;
    if (error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name)) throw new PublicRouteError("timeout", "Public health check timed out after 3 seconds");
    const cause = error instanceof Error ? error.cause as { code?: unknown } | undefined : undefined;
    const code = typeof cause?.code === "string" && /^[A-Z0-9_]{1,64}$/.test(cause.code) ? ` (${cause.code})` : "";
    throw new PublicRouteError("network_error", `Public health connection failed${code}`);
  }
}
export async function waitForPublicService(base: string, instanceId: string, signal: AbortSignal, timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  const bounded = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]);
  do {
    try { await probePublicService(base, instanceId, bounded); return; }
    catch { bounded.throwIfAborted(); }
    await delay(500, undefined, { signal: bounded });
  } while (Date.now() < deadline);
  throw new Error("Public route did not become reachable");
}
/** Serial probes, no overlap. Stop aborts requests and drains the monitor. */
export interface NetworkHealthMonitorOptions {
  readonly keepRunningOnFailure?: boolean;
  readonly onProbeResult?: (result: { ok: boolean; failures: number; error?: Error }) => void;
}
export class NetworkHealthMonitor {
  #controller = new AbortController();
  #work: Promise<void> | undefined;
  constructor(readonly probe: (signal: AbortSignal) => Promise<void>, readonly failed: (error: Error) => void, readonly intervalMs = 15000, readonly options: NetworkHealthMonitorOptions = {}) {}
  start(): void {
    if (this.#work) throw new Error("Health monitor already started");
    this.#work = this.#run();
  }
  async #run(): Promise<void> {
    let failures = 0;
    try {
      while (!this.#controller.signal.aborted) {
        await delay(this.intervalMs, undefined, { signal: this.#controller.signal, ref: false });
        try {
          await this.probe(this.#controller.signal);
          if (this.#controller.signal.aborted) return;
          failures = 0; this.options.onProbeResult?.({ ok: true, failures });
        } catch (error) {
          if (this.#controller.signal.aborted) return;
          failures++;
          const failure = error instanceof Error ? error : new Error("Public health check failed");
          this.options.onProbeResult?.({ ok: false, failures, error: failure });
          if (failures === 3) {
            this.failed(new Error(`Public MCP route failed three consecutive health checks: ${failure.message}`));
            if (!this.options.keepRunningOnFailure) return;
          }
        }
      }
    } catch { /* owned cancellation */ }
  }
  async stop(): Promise<void> { this.#controller.abort(); await this.#work; }
}
