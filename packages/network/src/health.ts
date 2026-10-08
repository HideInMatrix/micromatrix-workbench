import { setTimeout as delay } from "node:timers/promises";

/** An owned service nonce, not just HTTP 200 or a printed URL. No credentials
 * are sent. Redirects and unbounded bodies are refused. */
export async function probePublicService(base: string, instanceId: string, signal?: AbortSignal): Promise<void> {
  const abort = AbortSignal.timeout(3000);
  const response = await fetch(`${base}/healthz`, { redirect: "error", headers: { "ngrok-skip-browser-warning": "1" },
    signal: signal ? AbortSignal.any([signal, abort]) : abort });
  if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) { await response.body?.cancel(); throw new Error("Public route did not return service health JSON"); }
  let size = 0; const chunks: Uint8Array[] = [];
  if (response.body) for await (const chunk of response.body) {
    size += chunk.length;
    if (size > 16384) { await response.body.cancel().catch(() => {}); throw new Error("Public health response exceeded limit"); }
    chunks.push(chunk);
  }
  const health: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!health || typeof health !== "object" || Reflect.get(health, "ok") !== true || Reflect.get(health, "instance_id") !== instanceId) throw new Error("Public route reaches a different service instance");
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
export class NetworkHealthMonitor {
  #controller = new AbortController();
  #work: Promise<void> | undefined;
  constructor(readonly probe: (signal: AbortSignal) => Promise<void>, readonly failed: (error: Error) => void, readonly intervalMs = 15000) {}
  start(): void {
    if (this.#work) throw new Error("Health monitor already started");
    this.#work = this.#run();
  }
  async #run(): Promise<void> {
    let failures = 0;
    try {
      while (!this.#controller.signal.aborted) {
        await delay(this.intervalMs, undefined, { signal: this.#controller.signal, ref: false });
        try { await this.probe(this.#controller.signal); failures = 0; }
        catch { if (this.#controller.signal.aborted) return; if (++failures >= 3) { this.failed(new Error("Public MCP route failed three consecutive health checks")); return; } }
      }
    } catch { /* owned cancellation */ }
  }
  async stop(): Promise<void> { this.#controller.abort(); await this.#work; }
}
