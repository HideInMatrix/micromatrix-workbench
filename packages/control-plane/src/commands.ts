import type { ControlPlaneOptions, DesktopApiRequest, RuntimeSnapshot, RuntimeTool, SecretUpdate } from "./types.js";

export class UnsupportedDesktopCommandError extends Error {
  constructor(method: string) {
    super(`Unsupported desktop command: ${method}`);
    this.name = "UnsupportedDesktopCommandError";
  }
}

function providerDefinitions() {
  return [
    {
      key: "external",
      label: "External URL",
      supports_public_url: true,
      ephemeral_without_public_url: false,
      options: [],
    },
    {
      key: "cloudflare",
      label: "Cloudflare Tunnel",
      supports_public_url: true,
      ephemeral_without_public_url: true,
      options: [
        { key: "executable", label: "cloudflared 路径（可选）", secret: false, span: "2" },
        { key: "tunnel_token", label: "Tunnel Token", secret: true, span: "2" },
      ],
    },
    {
      key: "ngrok",
      label: "ngrok",
      supports_public_url: true,
      ephemeral_without_public_url: true,
      options: [
        { key: "executable", label: "ngrok 路径（可选）", secret: false, span: "2" },
        { key: "auth_token", label: "Auth Token", secret: true, span: "2" },
      ],
    },
    {
      key: "frp",
      label: "FRP",
      supports_public_url: true,
      ephemeral_without_public_url: false,
      options: [
        { key: "executable", label: "frpc 路径（可选）", secret: false, span: "2" },
        { key: "config_file", label: "frpc 配置文件", secret: false, span: "2" },
      ],
    },
    {
      key: "tailscale",
      label: "Tailscale Funnel",
      supports_public_url: true,
      ephemeral_without_public_url: false,
      options: [
        { key: "executable", label: "tailscale 路径（可选）", secret: false, span: "2" },
      ],
    },
  ];
}

function runtimeDto(runtime: RuntimeSnapshot) {
  const publicUrl = runtime.configuredPublicUrl.replace(/\/mcp\/?$/, "").replace(/\/$/, "");
  const optionDefinitions = providerDefinitions().flatMap((provider) => provider.options);
  const allowedOptions = new Set(optionDefinitions.map((option) => option.key));
  const secretOptions = new Set(optionDefinitions.filter((option) => option.secret).map((option) => option.key));
  return {
    runtime_id: runtime.runtimeId,
    name: runtime.name,
    workspace: runtime.workspace,
    has_oauth_password: runtime.oauthEnabled,
    remember_secrets: runtime.rememberSecrets,
    host: runtime.host,
    port: runtime.port,
    permission_mode: runtime.permissionMode,
    network: {
      provider: runtime.networkProvider,
      public_url: publicUrl,
      options: Object.fromEntries(Object.entries(runtime.networkOptions)
        .filter(([key]) => allowedOptions.has(key) && !secretOptions.has(key))),
      configured_secrets: [...secretOptions].filter((key) => Boolean(runtime.networkOptions[key])),
    },
    running: runtime.running,
    public_mcp_url: runtime.publicMcpUrl,
    url_mode: runtime.urlMode,
    exit_reason: runtime.exitReason,
  };
}

function effectiveTool(tool: RuntimeTool) {
  return {
    provider: "system",
    tool_name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema,
    key: `system:${tool.name}`,
  };
}

function capability(tool: RuntimeTool) {
  return {
    id: `builtin:${tool.name}`,
    type: "builtin_tool",
    name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema,
    tags: ["pi", tool.pluginId],
    source: { plugin_id: tool.pluginId },
    availability: { status: "available", reasons: [] },
    execution: {
      owner: "workbench_runtime",
      required_capabilities: [],
      required_operation_permissions: [],
      annotations: {
        read_only: tool.name === "read" || tool.name === "grep" || tool.name === "find" || tool.name === "ls",
        destructive: tool.name === "bash" || tool.name === "edit" || tool.name === "write",
        idempotent: false,
        open_world: tool.name === "bash",
      },
      permission_boundary: "Pi tool plugin",
      approval_boundary: "MCP client and local policy",
    },
    invocation: { tool_name: tool.name },
  };
}

export class DesktopCommandRouter {
  readonly #options: ControlPlaneOptions;

  constructor(options: ControlPlaneOptions) {
    this.#options = options;
  }

  async dispatch(request: DesktopApiRequest): Promise<unknown> {
    const runtime = this.#options.runtime.snapshot();
    const runtimeView = runtimeDto(runtime);
    switch (request.method) {
      case "bootstrap":
        return {
          app_name: this.#options.appName,
          version: this.#options.version,
          runtime: runtimeView,
          network_providers: providerDefinitions(),
        };
      case "get_app_version": return this.#options.version;
      case "get_runtime": return runtimeView;
      case "configure_runtime": {
        await this.#options.runtime.configure(this.#configuration(request.args[0]));
        return runtimeDto(this.#options.runtime.snapshot());
      }
      case "start_runtime":
        await this.#options.runtime.start();
        return runtimeDto(this.#options.runtime.snapshot());
      case "stop_runtime":
        await this.#options.runtime.stop();
        return runtimeDto(this.#options.runtime.snapshot());
      case "list_body_plugins":
        return runtime.pluginIds.map((id) => ({
          id,
          name: id === "workspace" ? "Workspace Tools" : id === "shell" ? "Shell Tool" : id,
          enabled: id === "workspace" || runtime.enableShell,
          required: id === "workspace",
        }));
      case "set_body_plugin_enabled":
        await this.#options.runtime.setPluginEnabled(String(request.args[0] ?? ""), Boolean(request.args[1]));
        return true;
      case "list_permission_requests":
        return (this.#options.approvals?.requests() ?? []).map((request) => ({
          request_id: request.requestId,
          runtime_id: runtime.runtimeId,
          runtime_name: runtime.name,
          tool_name: request.toolName,
          permission: request.permission,
          reason: request.reason,
          arguments: request.arguments,
          client_id: request.context.clientId ?? "",
          client_name: request.context.clientName ?? request.context.subjectId,
          authentication: request.context.authentication,
          created_at: request.createdAt,
          expires_at: request.expiresAt,
        }));
      case "respond_permission_request":
        return this.#options.approvals?.respond(
          String(request.args[0] ?? ""),
          String(request.args[1] ?? "deny") as "deny" | "once" | "session",
        ) ?? false;
      case "get_logs": return this.#options.logs.entries(Number(request.args[0] ?? 0));
      case "clear_logs": return this.#options.logs.clear();
      case "get_workbench_capability_catalog":
        return {
          skills: [],
          tools: runtime.tools.map((tool) => tool.name),
          effective_tools: runtime.tools.map(effectiveTool),
          mcp_connections: [],
          capabilities: runtime.tools.map(capability),
          revision: `${this.#options.version}:${runtime.tools.map((tool) => tool.name).join(",")}`,
        };
      case "choose_workspace": return "";
      default: throw new UnsupportedDesktopCommandError(request.method);
    }
  }

  #configuration(value: unknown) {
    if (!value || typeof value !== "object") throw new Error("Runtime configuration must be an object");
    const network = Reflect.get(value, "network");
    if (!network || typeof network !== "object") throw new Error("Network configuration is required");
    const provider = String(Reflect.get(network, "provider") ?? "external");
    if (!["external", "cloudflare", "frp", "ngrok", "tailscale"].includes(provider)) {
      throw new Error(`Unsupported network provider: ${provider}`);
    }
    const mode = String(Reflect.get(value, "permission_mode") ?? "safe");
    if (!["safe", "trusted", "dangerous"].includes(mode)) throw new Error(`Unsupported permission mode: ${mode}`);
    const options = Reflect.get(network, "options");
    const secretUpdates = Reflect.get(network, "secret_updates");
    const definition = providerDefinitions().find((item) => item.key === provider);
    const ordinaryKeys = new Set(definition?.options.filter((item) => !item.secret).map((item) => item.key) ?? []);
    const secretKeys = new Set(definition?.options.filter((item) => item.secret).map((item) => item.key) ?? []);
    const parsedOptions = options && typeof options === "object"
      ? Object.fromEntries(Object.entries(options)
        .filter(([key]) => ordinaryKeys.has(key))
        .map(([key, item]) => [key, String(item)]))
      : {};
    const parsedSecretUpdates = secretUpdates && typeof secretUpdates === "object"
      ? Object.fromEntries(Object.entries(secretUpdates)
        .filter(([key]) => secretKeys.has(key))
        .map(([key, item]) => [key, parseSecretUpdate(item, `network.${key}`)]))
      : {};
    return {
      name: String(Reflect.get(value, "name") ?? "Pi MCP Runtime"),
      workspace: String(Reflect.get(value, "workspace") ?? ""),
      host: String(Reflect.get(value, "host") ?? "127.0.0.1"),
      port: Number(Reflect.get(value, "port") ?? 8234),
      permissionMode: mode as "safe" | "trusted" | "dangerous",
      oauthPassword: parseSecretUpdate(Reflect.get(value, "oauth_password_update"), "oauth_password"),
      rememberSecrets: Boolean(Reflect.get(value, "remember_secrets")),
      network: {
        provider: provider as "external" | "cloudflare" | "frp" | "ngrok" | "tailscale",
        publicUrl: String(Reflect.get(network, "public_url") ?? ""),
        options: parsedOptions,
        secretUpdates: parsedSecretUpdates,
      },
    };
  }
}

function parseSecretUpdate(value: unknown, label: string): SecretUpdate {
  if (value === undefined || value === null) return { action: "unchanged" };
  if (typeof value !== "object") throw new Error(`${label} update must be an object`);
  const action = String(Reflect.get(value, "action") ?? "unchanged");
  if (action === "unchanged" || action === "clear") return { action };
  if (action !== "set") throw new Error(`Unsupported ${label} secret action: ${action}`);
  const secret = String(Reflect.get(value, "value") ?? "");
  if (!secret) throw new Error(`${label} cannot be empty when action is set`);
  return { action: "set", value: secret };
}
