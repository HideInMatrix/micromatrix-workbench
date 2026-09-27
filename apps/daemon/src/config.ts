import { resolve } from "node:path";

export interface DaemonConfig {
  readonly workspace: string;
  readonly host: string;
  readonly port: number;
  readonly authToken: string | undefined;
  readonly enableShell: boolean;
  readonly network:
    | { readonly provider: "external"; readonly publicUrl: string | undefined }
    | {
        readonly provider: "cloudflare";
        readonly executable: string;
        readonly publicUrl: string | undefined;
        readonly tunnelToken: string | undefined;
      };
}

function first(env: NodeJS.ProcessEnv, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = env[key]?.trim();
    if (value) return value;
  }
  return undefined;
}

function boolean(value: string | undefined): boolean {
  return value !== undefined && ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): DaemonConfig {
  const portText = first(env, "MICROMATRIX_PORT", "AGENT_RUNTIME_PORT") ?? "8234";
  const port = Number.parseInt(portText, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`Invalid MICROMATRIX_PORT: ${portText}`);
  }

  const provider = (
    first(env, "MICROMATRIX_NETWORK_PROVIDER", "AGENT_RUNTIME_NETWORK_PROVIDER") ?? "external"
  ).toLowerCase();
  const publicUrl = first(env, "MICROMATRIX_PUBLIC_URL", "AGENT_RUNTIME_SERVER_URL");
  const common = {
    workspace: resolve(first(env, "MICROMATRIX_WORKSPACE", "AGENT_RUNTIME_WORKSPACE") ?? "."),
    host: first(env, "MICROMATRIX_HOST", "AGENT_RUNTIME_HOST") ?? "127.0.0.1",
    port,
    authToken: first(env, "MICROMATRIX_AUTH_TOKEN"),
    enableShell: boolean(first(env, "MICROMATRIX_ENABLE_SHELL")),
  };

  if (provider === "external") {
    return { ...common, network: { provider, publicUrl } };
  }
  if (provider === "cloudflare") {
    return {
      ...common,
      network: {
        provider,
        executable: first(env, "MICROMATRIX_CLOUDFLARED") ?? "cloudflared",
        publicUrl,
        tunnelToken: first(env, "MICROMATRIX_TUNNEL_TOKEN", "AGENT_RUNTIME_TUNNEL_TOKEN"),
      },
    };
  }
  throw new Error(`Unsupported network provider: ${provider}`);
}
