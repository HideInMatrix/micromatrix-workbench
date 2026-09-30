import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { assertExecutable } from "./process.js";
import {
  providerResult,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
  type TailscaleProviderOptions,
} from "./types.js";

const execFileAsync = promisify(execFile);

export class TailscaleNetworkProvider implements NetworkProvider {
  readonly key = "tailscale";
  readonly #options: TailscaleProviderOptions;
  #active = false;

  constructor(options: TailscaleProviderOptions) {
    if (!options.publicUrl) throw new Error("Tailscale Funnel requires its HTTPS public URL");
    this.#options = options;
  }

  async preflight(): Promise<void> {
    await assertExecutable(this.#options.executable);
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    const { stdout, stderr } = await execFileAsync(
      this.#options.executable,
      ["funnel", "--bg", "--yes", context.localBaseUrl],
      { timeout: 30_000 },
    );
    context.logger.log("debug", "[tailscale] funnel configured", {
      output: `${stdout}${stderr}`.trim(),
    });
    this.#active = true;
    return providerResult(this.key, this.#options.publicUrl, "Tailscale Funnel");
  }

  async stop(): Promise<void> {
    if (!this.#active) return;
    this.#active = false;
    await execFileAsync(this.#options.executable, ["funnel", "reset"], { timeout: 15_000 });
  }
}
