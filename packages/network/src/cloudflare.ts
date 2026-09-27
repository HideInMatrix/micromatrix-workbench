import { ManagedProcess } from "./process.js";
import {
  providerResult,
  type CloudflareProviderOptions,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
} from "./types.js";

const QUICK_TUNNEL_URL = /https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com/;

export class CloudflareNetworkProvider implements NetworkProvider {
  readonly key = "cloudflare";
  readonly #options: CloudflareProviderOptions;
  #process: ManagedProcess | undefined;

  constructor(options: CloudflareProviderOptions) {
    if (Boolean(options.publicUrl) !== Boolean(options.tunnelToken)) {
      throw new Error("Cloudflare Named Tunnel requires both publicUrl and tunnelToken");
    }
    this.#options = options;
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    this.#process = new ManagedProcess(context.logger);
    if (this.#options.publicUrl && this.#options.tunnelToken) {
      this.#process.start(
        this.#options.executable,
        ["tunnel", "--protocol", "auto", "run", "--token", this.#options.tunnelToken],
        "cloudflared",
      );
      await this.#process.waitFor(
        (line) => line.toLowerCase().includes("registered tunnel connection"),
        60_000,
        "Cloudflare Named Tunnel connection",
      );
      return providerResult(this.key, this.#options.publicUrl, "Cloudflare Named Tunnel");
    }

    this.#process.start(
      this.#options.executable,
      ["tunnel", "--protocol", "auto", "--url", context.localBaseUrl],
      "cloudflared",
    );
    const line = await this.#process.waitFor(
      (candidate) => QUICK_TUNNEL_URL.test(candidate),
      60_000,
      "Cloudflare Quick Tunnel URL",
    );
    const publicUrl = line.match(QUICK_TUNNEL_URL)?.[0];
    if (!publicUrl) throw new Error("cloudflared output did not contain a tunnel URL");
    return providerResult(this.key, publicUrl, "Cloudflare Quick Tunnel");
  }

  async stop(): Promise<void> {
    await this.#process?.stop();
    this.#process = undefined;
  }
}
