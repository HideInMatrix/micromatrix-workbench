import { ManagedProcess } from "./process.js";
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

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    this.#process = new ManagedProcess(context.logger);
    this.#process.start(this.#options.executable, ["-c", this.#options.configFile], "frpc");
    await this.#process.waitFor(
      (line) => /login to server success|start proxy success|start .*proxy/i.test(line),
      30_000,
      "FRP client connection",
    );
    return providerResult(this.key, this.#options.publicUrl, "FRP");
  }

  async stop(): Promise<void> {
    await this.#process?.stop();
    this.#process = undefined;
  }
}
