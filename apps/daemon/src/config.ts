import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";

import type { ApprovalMode } from "@micromatrix/approval";

export type NetworkProviderKey = "external" | "cloudflare" | "frp" | "ngrok" | "tailscale";

export interface DaemonConfig {
  readonly configFile: string;
  readonly name: string;
  readonly workspace: string;
  readonly host: string;
  readonly port: number;
  readonly authToken: string | undefined;
  readonly oauthPassword: string | undefined;
  readonly rememberSecrets: boolean;
  readonly permissionMode: ApprovalMode;
  readonly plugins: { readonly shell: boolean };
  readonly controlHost: string;
  readonly controlPort: number;
  readonly network: {
    readonly provider: NetworkProviderKey;
    readonly publicUrl: string | undefined;
    readonly options: Readonly<Record<string, string>>;
  };
}

interface SavedConfig {
  readonly name?: string;
  readonly workspace?: string;
  readonly host?: string;
  readonly port?: number;
  readonly oauthPassword?: string;
  readonly rememberSecrets?: boolean;
  readonly permissionMode?: ApprovalMode;
  readonly plugins?: { readonly shell?: boolean };
  readonly network?: {
    readonly provider?: NetworkProviderKey;
    readonly publicUrl?: string;
    readonly options?: Readonly<Record<string, string>>;
  };
}

function first(env: NodeJS.ProcessEnv, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = env[key]?.trim();
    if (value) return value;
  }
  return undefined;
}

function boolean(value: string | undefined, fallback = false): boolean {
  if (value === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function port(value: string | number | undefined, name: string, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number.parseInt(value ?? String(fallback), 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65_535) throw new Error(`Invalid ${name}: ${String(value)}`);
  return parsed;
}

function saved(path: string): SavedConfig {
  try { return JSON.parse(readFileSync(path, "utf8")) as SavedConfig; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw new Error(`Cannot load runtime config ${path}: ${String(error)}`);
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): DaemonConfig {
  const configFile = resolve(first(env, "MICROMATRIX_CONFIG_FILE") ?? `${homedir()}/.micromatrix-pi-mcp/runtime.json`);
  const disk = saved(configFile);
  const provider = (first(env, "MICROMATRIX_NETWORK_PROVIDER", "AGENT_RUNTIME_NETWORK_PROVIDER") ?? disk.network?.provider ?? "external").toLowerCase();
  if (!["external", "cloudflare", "frp", "ngrok", "tailscale"].includes(provider)) throw new Error(`Unsupported network provider: ${provider}`);
  const permissionMode = (first(env, "MICROMATRIX_PERMISSION_MODE") ?? disk.permissionMode ?? "safe") as ApprovalMode;
  if (!["safe", "trusted", "dangerous"].includes(permissionMode)) throw new Error(`Unsupported permission mode: ${permissionMode}`);
  const runtimePort = port(first(env, "MICROMATRIX_PORT", "AGENT_RUNTIME_PORT") ?? disk.port, "MICROMATRIX_PORT", 8234);
  const controlPort = port(first(env, "MICROMATRIX_CONTROL_PORT"), "MICROMATRIX_CONTROL_PORT", 8233);
  if (controlPort === runtimePort) throw new Error("MICROMATRIX_CONTROL_PORT must differ from MICROMATRIX_PORT");

  const networkOptions: Record<string, string> = { ...(disk.network?.options ?? {}) };
  const optionEnv: Readonly<Record<string, string>> = {
    executable: first(env, "MICROMATRIX_TUNNEL_EXECUTABLE", "MICROMATRIX_CLOUDFLARED") ?? "",
    tunnel_token: first(env, "MICROMATRIX_TUNNEL_TOKEN", "AGENT_RUNTIME_TUNNEL_TOKEN") ?? "",
    protocol: first(env, "MICROMATRIX_CLOUDFLARE_PROTOCOL") ?? "",
    auth_token: first(env, "MICROMATRIX_NGROK_AUTH_TOKEN") ?? "",
    config_file: first(env, "MICROMATRIX_FRP_CONFIG") ?? "",
  };
  for (const [key, value] of Object.entries(optionEnv)) if (value) networkOptions[key] = value;

  return {
    configFile,
    name: first(env, "MICROMATRIX_NAME") ?? disk.name ?? "Pi MCP Runtime",
    workspace: resolve(first(env, "MICROMATRIX_WORKSPACE", "AGENT_RUNTIME_WORKSPACE") ?? disk.workspace ?? "."),
    host: first(env, "MICROMATRIX_HOST", "AGENT_RUNTIME_HOST") ?? disk.host ?? "127.0.0.1",
    port: runtimePort,
    authToken: first(env, "MICROMATRIX_AUTH_TOKEN"),
    oauthPassword: first(env, "MICROMATRIX_OAUTH_PASSWORD") ?? disk.oauthPassword,
    rememberSecrets: boolean(first(env, "MICROMATRIX_REMEMBER_SECRETS"), disk.rememberSecrets ?? true),
    permissionMode,
    plugins: { shell: boolean(first(env, "MICROMATRIX_ENABLE_SHELL"), disk.plugins?.shell ?? false) },
    controlHost: first(env, "MICROMATRIX_CONTROL_HOST") ?? "127.0.0.1",
    controlPort,
    network: {
      provider: provider as NetworkProviderKey,
      publicUrl: first(env, "MICROMATRIX_PUBLIC_URL", "AGENT_RUNTIME_SERVER_URL") ?? disk.network?.publicUrl,
      options: networkOptions,
    },
  };
}

export function saveConfig(config: DaemonConfig, rememberSecrets: boolean): void {
  const safeOptions = Object.fromEntries(Object.entries(config.network.options).filter(([key]) => (
    rememberSecrets || !/token|secret|password|key/i.test(key)
  )));
  const value: SavedConfig = {
    name: config.name,
    workspace: config.workspace,
    host: config.host,
    port: config.port,
    ...(rememberSecrets && config.oauthPassword ? { oauthPassword: config.oauthPassword } : {}),
    rememberSecrets,
    permissionMode: config.permissionMode,
    plugins: config.plugins,
    network: {
      provider: config.network.provider,
      ...(config.network.publicUrl ? { publicUrl: config.network.publicUrl } : {}),
      options: safeOptions,
    },
  };
  mkdirSync(dirname(config.configFile), { recursive: true, mode: 0o700 });
  const temporary = `${config.configFile}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporary, config.configFile);
}
