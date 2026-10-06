import type { ExtensionConfiguration, McpConnectionConfig } from "@micromatrix/plugin-kit";

export interface ComputerUsePermissionStatus {
  readonly platform: "macos" | "windows";
  readonly helperPath: string;
  readonly accessibility?: boolean;
  readonly interactiveDesktop?: boolean;
  readonly elevated?: boolean;
  readonly promptRequested: boolean;
  readonly requiresScreenRecording: false;
}
export interface BuiltinComputerUseStatus {
  readonly enabled: boolean;
  readonly allowActions: boolean;
  readonly supported: boolean;
  readonly available: boolean;
  readonly platform: string;
  readonly helperPath: string;
  readonly running: boolean;
  readonly connected: boolean;
  readonly permission: ComputerUsePermissionStatus | null;
  readonly checkedAt: number;
  readonly error: string;
  readonly conflict: boolean;
}

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
  readonly extensions?: ExtensionConfiguration;
  readonly skills?: readonly { readonly id: string; readonly name: string; readonly description: string; readonly disableModelInvocation: boolean }[];
  readonly extensionHostActive?: boolean;
  readonly mcpStatus?: Readonly<Record<string, { keys: string[]; oauth: string; status: string; message: string; discoveredAt: number }>>;
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
  computerUseStatus?(): BuiltinComputerUseStatus;
  setComputerUseEnabled?(enabled: boolean): Promise<void>;
  checkComputerUsePermissions?(request: boolean): Promise<BuiltinComputerUseStatus>;
  computerUseConnection?(): McpConnectionConfig;
  snapshot(): RuntimeSnapshot;
  start(): Promise<void>;
  stop(): Promise<void>;
  configure(update: RuntimeConfigurationUpdate): Promise<void>;
  setPluginEnabled(pluginId: string, enabled: boolean): Promise<void>;
  configureExtensions?(value: ExtensionConfiguration): Promise<void>;
  createSkill?(id: string, description: string, instructions: string): Promise<void>;
  setMcpCredentials?(id: string, updates: unknown): Promise<void>;
  beginMcpLogin?(id: string): Promise<{ url: string }>;
  cancelMcpLogin?(id: string): Promise<void>;
  logoutMcp?(id: string): Promise<void>;
  refreshMcpTools?(id: string): Promise<void>;
  skillDocuments?(): Promise<readonly { id: string; description: string }[]>;
  readSkill?(id: string): Promise<{ id: string; document: string; revision: string; files: readonly { path: string; size: number }[] }>;
  editSkill?(id: string, document: string, revision: string): Promise<void>;
  testMcpConnection?(value: McpConnectionConfig): Promise<{ readonly tools: readonly string[] }>;
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
