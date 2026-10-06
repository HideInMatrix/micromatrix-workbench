import type { ControlPlaneOptions, DesktopApiRequest, RuntimeSnapshot, RuntimeTool, SecretUpdate } from "./types.js";
import { EMPTY_EXTENSIONS, parseExtensions, parseMcpConnection } from "@micromatrix/plugin-kit";
import { createHash } from "node:crypto";

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
        {
          key: "protocol", label: "隧道传输协议", secret: false, span: "2",
          default_value: "auto",
          description: "控制 cloudflared 到 Cloudflare 的连接；本地 MCP 仍使用 HTTP。UDP 受限时选择 HTTP/2。",
          choices: [
            { value: "auto", label: "自动（QUIC 优先，失败回退 HTTP/2）" },
            { value: "http2", label: "HTTP/2（TCP）" },
            { value: "quic", label: "QUIC（UDP）" },
          ],
        },
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
  const external = tool.pluginId.startsWith("mcp:");
  return {
    provider: external ? "mcp" : "system",
    tool_name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema,
    key: `${external ? "mcp" : "system"}:${tool.name}`,
    ...(external ? { connection_id: tool.pluginId.slice(4) } : {}),
  };
}

function capability(tool: RuntimeTool) {
  const external = tool.pluginId.startsWith("mcp:");
  return {
    id: `${external ? "mcp" : "builtin"}:${tool.name}`,
    type: external ? "mcp_tool" : "builtin_tool",
    name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema,
    tags: ["pi", tool.pluginId],
    source: { plugin_id: tool.pluginId },
    availability: { status: "available", reasons: [] },
    execution: {
      owner: external ? "external_mcp" : "workbench_runtime",
      required_capabilities: [],
      required_operation_permissions: [],
      annotations: {
        read_only: tool.name === "read" || tool.name === "grep" || tool.name === "find" || tool.name === "ls",
        destructive: tool.name === "bash" || tool.name === "edit" || tool.name === "write",
        idempotent: false,
        open_world: external || tool.name === "bash",
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
      case "get_pi_extensions":
        return { configuration: runtime.extensions ?? EMPTY_EXTENSIONS, running: runtime.running,
          host_active: runtime.extensionHostActive ?? false, loaded_skills: runtime.skills ?? [], mcp_status: runtime.mcpStatus ?? {} };
      case "get_computer_use_mcp_template":
        if (!this.#options.runtime.computerUseConnection) throw new Error("Computer Use MCP template unavailable");
        return this.#options.runtime.computerUseConnection();
      case "get_computer_use_status":
        if (!this.#options.runtime.computerUseStatus) throw new Error("Built-in Computer Use unavailable");
        return this.#options.runtime.computerUseStatus();
      case "set_computer_use_enabled":
        if (!this.#options.runtime.setComputerUseEnabled) throw new Error("Built-in Computer Use unavailable");
        if (typeof request.args[0] !== "boolean") throw new Error("Computer Use enabled must be a boolean");
        await this.#options.runtime.setComputerUseEnabled(request.args[0]);
        return this.#options.runtime.computerUseStatus?.();
      case "check_computer_use_permissions":
        if (!this.#options.runtime.checkComputerUsePermissions) throw new Error("Computer Use permission check unavailable");
        if (request.args[0] !== undefined && typeof request.args[0] !== "boolean") throw new Error("Permission request must be a boolean");
        return this.#options.runtime.checkComputerUsePermissions(request.args[0] === true);
      case "configure_pi_extensions":
        if (!this.#options.runtime.configureExtensions) throw new Error("Pi extension management unavailable");
        await this.#options.runtime.configureExtensions(parseExtensions(request.args[0]));
        return true;
      case "create_pi_skill":
        if (!this.#options.runtime.createSkill) throw new Error("Pi Skill creation unavailable");
        await this.#options.runtime.createSkill(String(request.args[0] ?? ""), String(request.args[1] ?? ""), String(request.args[2] ?? ""));
        return true;
      case "test_pi_mcp":
        if (!this.#options.runtime.testMcpConnection) throw new Error("Pi MCP connection testing unavailable");
        return this.#options.runtime.testMcpConnection(parseMcpConnection(request.args[0]));
      case "set_pi_mcp_credentials":
        if (!this.#options.runtime.setMcpCredentials) throw new Error("MCP credential management unavailable");
        await this.#options.runtime.setMcpCredentials(String(request.args[0] ?? ""), request.args[1]); return true;
      case "login_pi_mcp":
        if (!this.#options.runtime.beginMcpLogin) throw new Error("MCP OAuth unavailable");
        return this.#options.runtime.beginMcpLogin(String(request.args[0] ?? ""));
      case "cancel_pi_mcp_login":
        await this.#options.runtime.cancelMcpLogin?.(String(request.args[0] ?? "")); return true;
      case "logout_pi_mcp":
        if (!this.#options.runtime.logoutMcp) throw new Error("MCP OAuth unavailable");
        await this.#options.runtime.logoutMcp(String(request.args[0] ?? "")); return true;
      case "refresh_pi_mcp":
        if (!this.#options.runtime.refreshMcpTools) throw new Error("MCP refresh unavailable");
        await this.#options.runtime.refreshMcpTools(String(request.args[0] ?? "")); return true;
      case "list_pi_skill_documents": return this.#options.runtime.skillDocuments?.() ?? [];
      case "read_pi_skill_document":
        if (!this.#options.runtime.readSkill) throw new Error("Skill editor unavailable");
        return this.#options.runtime.readSkill(String(request.args[0] ?? ""));
      case "edit_pi_skill_document":
        if (!this.#options.runtime.editSkill) throw new Error("Skill editor unavailable");
        await this.#options.runtime.editSkill(String(request.args[0] ?? ""), String(request.args[1] ?? ""), String(request.args[2] ?? "")); return true;
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
          skills: (runtime.skills ?? []).filter((skill) => !skill.disableModelInvocation).map((skill) => ({ ...skill, usage_hint: "Use skills_read with the Pi Skill ID",
            recommended_capabilities: [], version: 1, scope: "global", artifacts: [] })),
          tools: runtime.tools.map((tool) => tool.name),
          effective_tools: runtime.tools.map(effectiveTool),
          mcp_connections: (runtime.extensions?.mcp ?? []).map((connection) => ({ id: connection.id, name: connection.name,
            transport: connection.transport, endpoint: connection.url, command: connection.command, enabled: connection.enabled,
            version: 1, tool_count: runtime.tools.filter((tool) => tool.pluginId === `mcp:${connection.id}`).length,
            last_discovered_at: runtime.mcpStatus?.[connection.id]?.discoveredAt ?? 0,
            last_error: ["error", "test_failed", "disconnected"].includes(runtime.mcpStatus?.[connection.id]?.status ?? "") || runtime.mcpStatus?.[connection.id]?.oauth === "failed"
              ? runtime.mcpStatus?.[connection.id]?.message ?? "MCP connection failed" : "", health_tool: "", scope: "global" })),
          capabilities: [
            ...runtime.tools.map(capability),
            ...(runtime.skills ?? []).filter((skill) => !skill.disableModelInvocation).map((skill) => ({
              id: `skill:${skill.id}`, type: "skill", name: skill.name, description: skill.description,
              input_schema: { type: "object", properties: {} }, tags: ["pi", "skill"], source: { plugin_id: "skills" },
              availability: { status: "available", reasons: [] },
              execution: { owner: "ai_client", required_capabilities: ["builtin:skills_read"], required_operation_permissions: ["open_world"],
                annotations: { read_only: true, destructive: false, idempotent: true, open_world: false },
                permission_boundary: "Pi configured Skill resources", approval_boundary: "MCP client and local policy" },
              invocation: { tool_name: "skills_read", arguments: { id: skill.id } },
            })),
          ],
          revision: `${this.#options.version}:${createHash("sha256").update(JSON.stringify({ tools: runtime.tools,
            skills: runtime.skills ?? [], connections: runtime.extensions?.mcp.map(({ id, enabled }) => ({ id, enabled })) ?? [] })).digest("hex")}`,
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
    // Desktop uses its bundled Cloudflare client, so no path field is shown.
    // Preserve the existing API override for source development/integrations.
    if (provider === "cloudflare") ordinaryKeys.add("executable");
    const secretKeys = new Set(definition?.options.filter((item) => item.secret).map((item) => item.key) ?? []);
    const parsedOptions = options && typeof options === "object"
      ? Object.fromEntries(Object.entries(options)
        .filter(([key]) => ordinaryKeys.has(key))
        .map(([key, item]) => [key, String(item)]))
      : {};
    for (const field of definition?.options ?? []) {
      if (!field.choices) continue;
      const selected = parsedOptions[field.key] || field.default_value;
      if (!field.choices.some((choice) => choice.value === selected)) {
        throw new Error(`Invalid ${provider}.${field.key}: ${String(selected)}`);
      }
      parsedOptions[field.key] = selected;
    }
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
