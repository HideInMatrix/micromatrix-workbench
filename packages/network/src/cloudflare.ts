import { assertExecutable, ManagedProcess } from "./process.js";
import {
  providerResult,
  type CloudflareProviderOptions,
  type CloudflareTunnelProtocol,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
} from "./types.js";

const QUICK_TUNNEL_URL = /https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com/;

export function parseCloudflareProtocol(value: string | undefined): CloudflareTunnelProtocol {
  const protocol = value || "auto";
  if (protocol !== "auto" && protocol !== "http2" && protocol !== "quic") {
    throw new Error(`Unsupported Cloudflare Tunnel protocol: ${protocol}; use auto, http2 or quic`);
  }
  return protocol;
}

export class CloudflareNetworkProvider implements NetworkProvider {
  readonly key = "cloudflare";
  readonly #options: CloudflareProviderOptions;
  readonly #protocol: CloudflareTunnelProtocol;
  #process: ManagedProcess | undefined;

  constructor(options: CloudflareProviderOptions) {
    if (Boolean(options.publicUrl) !== Boolean(options.tunnelToken)) {
      throw new Error("Cloudflare Named Tunnel requires both publicUrl and tunnelToken");
    }
    this.#options = options;
    this.#protocol = parseCloudflareProtocol(options.protocol);
  }

  async preflight(): Promise<void> {
    await assertExecutable(this.#options.executable);
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    context.signal?.throwIfAborted();
    this.#process = new ManagedProcess(context.logger);
    if (this.#options.publicUrl && this.#options.tunnelToken) {
      this.#process.start(
        this.#options.executable,
        ["--no-autoupdate", "tunnel", "--protocol", this.#protocol, "run", "--token", this.#options.tunnelToken],
        "cloudflared",
      );
      await this.#waitForConnection(context.signal);
      this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
      return providerResult(this.key, this.#options.publicUrl, "Cloudflare Named Tunnel");
    }

    this.#process.start(
      this.#options.executable,
      ["--no-autoupdate", "tunnel", "--protocol", this.#protocol, "--url", context.localBaseUrl],
      "cloudflared",
    );
    const line = await this.#process.waitFor(
      (candidate) => QUICK_TUNNEL_URL.test(candidate),
      60_000,
      "Cloudflare Quick Tunnel URL",
      context.signal,
    );
    const publicUrl = line.match(QUICK_TUNNEL_URL)?.[0];
    if (!publicUrl) throw new Error("cloudflared output did not contain a tunnel URL");
    await this.#waitForConnection(context.signal);
    this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
    return providerResult(this.key, publicUrl, "Cloudflare Quick Tunnel");
  }

  async #waitForConnection(signal?: AbortSignal): Promise<void> {
    const managed = this.#process!;
    try {
      await managed.waitFor(
        (line) => line.toLowerCase().includes("registered tunnel connection"),
        60_000,
        "Cloudflare tunnel connection",
        signal,
      );
    } catch (error) {
      if (signal?.aborted) throw signal.reason;
      // Report only a fixed diagnostic, never raw log lines/tokens. Keep the
      // actual timeout/exit as cause. A URL is not evidence of connection.
      throw cloudflareConnectionError(managed.recentOutput(), error);
    }
  }

  async stop(force = false): Promise<void> {
    await this.#process?.stop(force);
    this.#process = undefined;
  }
}

/** Known upstream diagnostics, not raw stderr or token-bearing command args. */
export function cloudflareConnectionError(lines: readonly string[], cause: unknown): unknown {
  const output = lines.join("\n");
  const fakeIp = /(?:ip=|on |address[^\n]*)(?:198\.(?:18|19)\.)/.test(output);
  const blocked = /precheck.*component="(?:TCP|UDP) Connectivity".*status=fail/.test(output);
  if (!fakeIp && !blocked) return cause;
  return new Error(fakeIp
    ? "Cloudflare 未连接：代理 DNS 将边缘地址解析为 198.18.0.0/15 fake-IP；检查代理 DNS/分流，并允许 Tunnel 出站 TCP 或 UDP 7844。没有发布公网地址。"
    : "Cloudflare 未连接：连通性检查报告出站 7844 不可达；HTTP/2 使用 TCP，QUIC 使用 UDP。没有发布公网地址。", { cause });
}
