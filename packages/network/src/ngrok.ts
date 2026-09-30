import { assertExecutable, ManagedProcess } from "./process.js";
import {
  providerResult,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
  type NgrokProviderOptions,
} from "./types.js";

const NGROK_URL = /https:\/\/[a-zA-Z0-9.-]+(?:\.ngrok(?:-free)?\.(?:app|dev|io)|\.[a-zA-Z]{2,})(?=[\s"']|$)/;

export class NgrokNetworkProvider implements NetworkProvider {
  readonly key = "ngrok";
  readonly #options: NgrokProviderOptions;
  #process: ManagedProcess | undefined;

  constructor(options: NgrokProviderOptions) {
    this.#options = options;
  }

  async preflight(): Promise<void> {
    await assertExecutable(this.#options.executable);
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    this.#process = new ManagedProcess(context.logger);
    const args = ["http", "--log=stdout", "--log-format=json"];
    if (this.#options.authToken) args.push("--authtoken", this.#options.authToken);
    if (this.#options.publicUrl) args.push("--url", this.#options.publicUrl);
    args.push(context.localBaseUrl);
    this.#process.start(this.#options.executable, args, "ngrok");
    if (this.#options.publicUrl) {
      await this.#process.waitFor((line) => /started tunnel|url=/i.test(line), 30_000, "ngrok tunnel");
      this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
      return providerResult(this.key, this.#options.publicUrl, "ngrok");
    }
    const line = await this.#process.waitFor((candidate) => NGROK_URL.test(candidate), 30_000, "ngrok public URL");
    const publicUrl = line.match(NGROK_URL)?.[0];
    if (!publicUrl) throw new Error("ngrok output did not contain a public URL");
    this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
    return providerResult(this.key, publicUrl, "ngrok");
  }

  async stop(): Promise<void> {
    await this.#process?.stop();
    this.#process = undefined;
  }
}
