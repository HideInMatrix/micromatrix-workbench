import type { PluginLogger } from "@micromatrix/plugin-kit";

export interface NetworkProviderResult {
  readonly provider: string;
  readonly publicBaseUrl: string;
  readonly publicMcpUrl: string;
  readonly modeLabel: string;
}

export interface NetworkProviderContext {
  readonly localBaseUrl: string;
  readonly logger: PluginLogger;
  readonly onUnexpectedExit: (error: Error) => void;
}

export interface NetworkProvider {
  readonly key: string;
  preflight?(): Promise<void>;
  start(context: NetworkProviderContext): Promise<NetworkProviderResult>;
  stop(): Promise<void>;
}

export interface ExternalProviderOptions {
  readonly publicUrl: string;
}

export interface CloudflareProviderOptions {
  readonly executable: string;
  readonly publicUrl: string | undefined;
  readonly tunnelToken: string | undefined;
}

export interface FrpProviderOptions {
  readonly executable: string;
  readonly configFile: string;
  readonly publicUrl: string;
}

export interface NgrokProviderOptions {
  readonly executable: string;
  readonly publicUrl: string | undefined;
  readonly authToken: string | undefined;
}

export interface TailscaleProviderOptions {
  readonly executable: string;
  readonly publicUrl: string;
}

export function normalizeBaseUrl(value: string): string {
  const url = new URL(value.trim());
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Unsupported public URL protocol: ${url.protocol}`);
  }
  url.search = "";
  url.hash = "";
  url.pathname = url.pathname.replace(/\/mcp\/?$/, "").replace(/\/$/, "");
  return url.toString().replace(/\/$/, "");
}

export function providerResult(
  provider: string,
  publicBaseUrl: string,
  modeLabel: string,
): NetworkProviderResult {
  const normalized = normalizeBaseUrl(publicBaseUrl);
  return {
    provider,
    publicBaseUrl: normalized,
    publicMcpUrl: `${normalized}/mcp`,
    modeLabel,
  };
}
