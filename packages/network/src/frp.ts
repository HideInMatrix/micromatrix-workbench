import { assertExecutable, assertRegularFile, ManagedProcess } from "./process.js";
import {
  providerResult,
  type FrpProviderOptions,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
} from "./types.js";

export class FrpNetworkProvider implements NetworkProvider {
  readonly key = "frp";
  readonly #options: FrpProviderOptions;
  #process: ManagedProcess | undefined;

  constructor(options: FrpProviderOptions) {
    if (!options.configFile) throw new Error("FRP requires a client config file");
    if (!options.publicUrl) throw new Error("FRP requires its externally routed public URL");
    this.#options = options;
  }

  async preflight(): Promise<void> {
    await assertExecutable(this.#options.executable);
    await assertRegularFile(this.#options.configFile, "FRP config");
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    context.signal?.throwIfAborted();
    this.#process = new ManagedProcess(context.logger);
    this.#process.start(this.#options.executable, ["-c", this.#options.configFile], "frpc");
    await this.#process.waitFor(
      (line) => /start proxy success/i.test(line),
      30_000,
      "FRP client connection",
      context.signal,
    );
    this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
    return providerResult(this.key, this.#options.publicUrl, "FRP");
  }

  async stop(force = false): Promise<void> {
    await this.#process?.stop(force);
    this.#process = undefined;
  }
}
