import { assertExecutable, ManagedProcess } from "./process.js";
import {
  providerResult,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
  type NgrokProviderOptions,
} from "./types.js";

function startedUrl(line: string): string | undefined {
  try {
    const event = JSON.parse(line);
    if (event.msg !== "started tunnel" || typeof event.url !== "string") return undefined;
    const url = new URL(event.url);
    if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) return undefined;
    return url.origin;
  } catch { return undefined; }
}

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
    context.signal?.throwIfAborted();
    this.#process = new ManagedProcess(context.logger);
    const args = ["http", "--log=stdout", "--log-format=json"];
    if (this.#options.authToken) args.push("--authtoken", this.#options.authToken);
    if (this.#options.publicUrl) args.push("--url", this.#options.publicUrl);
    args.push(context.localBaseUrl);
    this.#process.start(this.#options.executable, args, "ngrok");
    const line = await this.#process.waitFor(candidate => {
      const url = startedUrl(candidate);
      return Boolean(url && (!this.#options.publicUrl || url === new URL(this.#options.publicUrl).origin));
    }, 30000, "ngrok started tunnel event", context.signal);
    const publicUrl = startedUrl(line)!;
    this.#process.monitorUnexpectedExit(context.onUnexpectedExit);
    return providerResult(this.key, publicUrl, "ngrok");
  }

  async stop(): Promise<void> {
    await this.#process?.stop();
    this.#process = undefined;
  }
}
