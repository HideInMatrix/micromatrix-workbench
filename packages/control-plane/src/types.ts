export interface DesktopApiRequest {
  readonly method: string;
  readonly args: readonly unknown[];
}

export interface RuntimeSnapshot {
  readonly runtimeId: string;
  readonly name: string;
  readonly workspace: string;
  readonly host: string;
  readonly port: number;
  readonly running: boolean;
  readonly publicMcpUrl: string;
  readonly urlMode: string;
  readonly exitReason: string;
  readonly networkProvider: "external" | "cloudflare" | "frp" | "ngrok" | "tailscale";
  readonly configuredPublicUrl: string;
  readonly enableShell: boolean;
  readonly oauthEnabled: boolean;
  readonly rememberSecrets: boolean;
  readonly permissionMode: "safe" | "trusted" | "dangerous";
  readonly networkOptions: Readonly<Record<string, string>>;
  readonly pluginIds: readonly string[];
  readonly tools: readonly RuntimeTool[];
}

export interface RuntimeConfigurationUpdate {
  readonly name: string;
  readonly workspace: string;
  readonly host: string;
  readonly port: number;
  readonly permissionMode: "safe" | "trusted" | "dangerous";
  readonly oauthPassword: SecretUpdate;
  readonly rememberSecrets: boolean;
  readonly network: {
    readonly provider: "external" | "cloudflare" | "frp" | "ngrok" | "tailscale";
    readonly publicUrl: string;
    readonly options: Readonly<Record<string, string>>;
    readonly secretUpdates: Readonly<Record<string, SecretUpdate>>;
  };
}

export type SecretUpdate =
  | { readonly action: "unchanged" }
  | { readonly action: "set"; readonly value: string }
  | { readonly action: "clear" };

export interface RuntimeTool {
  readonly name: string;
  readonly description: string;
  readonly inputSchema: Readonly<Record<string, unknown>>;
  readonly pluginId: string;
}

export interface RuntimeControl {
  snapshot(): RuntimeSnapshot;
  start(): Promise<void>;
  stop(): Promise<void>;
  configure(update: RuntimeConfigurationUpdate): Promise<void>;
  setPluginEnabled(pluginId: string, enabled: boolean): Promise<void>;
}

export interface ControlPlaneOptions {
  readonly appName: string;
  readonly version: string;
  readonly host: string;
  readonly port: number;
  readonly runtime: RuntimeControl;
  readonly logs: LogStore;
  readonly approvals?: ApprovalControl;
  readonly webAssets?: Readonly<Record<string, { readonly contentType: string; readonly bodyBase64: string }>>;
}

export interface ApprovalRequestSnapshot {
  readonly requestId: string;
  readonly toolName: string;
  readonly permission: string;
  readonly reason: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly context: {
    readonly clientId?: string;
    readonly clientName?: string;
    readonly subjectId: string;
    readonly sessionId: string;
    readonly authentication: "anonymous" | "static_bearer" | "oauth";
  };
  readonly createdAt: number;
  readonly expiresAt: number;
}

export interface ApprovalControl {
  requests(): readonly ApprovalRequestSnapshot[];
  respond(requestId: string, decision: "deny" | "once" | "session"): boolean;
}

export interface LogEntry {
  readonly id: number;
  readonly time: number;
  readonly message: string;
}

export interface LogStore {
  entries(after: number): { readonly cursor: number; readonly entries: readonly LogEntry[] };
  clear(): number;
}
