import {
  normalizeBaseUrl,
  providerResult,
  type ExternalProviderOptions,
  type NetworkProvider,
  type NetworkProviderContext,
  type NetworkProviderResult,
} from "./types.js";

export class ExternalNetworkProvider implements NetworkProvider {
  readonly key = "external";
  readonly #options: ExternalProviderOptions;

  constructor(options: ExternalProviderOptions) {
    this.#options = options;
  }

  async start(context: NetworkProviderContext): Promise<NetworkProviderResult> {
    const publicUrl = normalizeBaseUrl(this.#options.publicUrl);
    context.logger.log("info", "Using external network endpoint", {
      publicUrl,
      origin: context.localBaseUrl,
    });
    return providerResult(this.key, publicUrl, "External URL");
  }

  async stop(): Promise<void> {}
}
