import { stat } from "node:fs/promises";

import { ApprovalPolicy, type ApprovalMode } from "@micromatrix/approval";
import type { RuntimeConfigurationUpdate, RuntimeControl, RuntimeSnapshot } from "@micromatrix/control-plane";
import { McpHttpService } from "@micromatrix/mcp-server";
import {
  CloudflareNetworkProvider,
  ExternalNetworkProvider,
  FrpNetworkProvider,
  NgrokNetworkProvider,
  TailscaleNetworkProvider,
  type NetworkProvider,
  type NetworkProviderResult,
} from "@micromatrix/network";
import { LocalOAuthServer } from "@micromatrix/oauth";
import { PluginRegistry, type PluginLogger } from "@micromatrix/plugin-kit";
import { createShellPlugin } from "@micromatrix/plugin-shell";
import { createWorkspacePlugin } from "@micromatrix/plugin-workspace";

import { saveConfig, type DaemonConfig } from "./config.js";

export class RuntimeSupervisor implements RuntimeControl {
  #config: DaemonConfig;
  readonly #logger: PluginLogger;
  readonly approval: ApprovalPolicy;
  #registry: PluginRegistry;
  #service: McpHttpService;
  #provider: NetworkProvider;
  #network: NetworkProviderResult | undefined;
  #running = false;
  #transition: Promise<void> | undefined;
  #exitReason = "";

  constructor(config: DaemonConfig, logger: PluginLogger) {
    this.#config = config;
    this.#logger = logger;
    this.approval = new ApprovalPolicy(config.permissionMode);
    const parts = this.#createParts();
    this.#registry = parts.registry;
    this.#service = parts.service;
    this.#provider = parts.provider;
  }

  snapshot(): RuntimeSnapshot {
    return {
      runtimeId: "default",
      name: this.#config.name,
      workspace: this.#config.workspace,
      host: this.#config.host,
      port: this.#config.port,
      running: this.#running,
      publicMcpUrl: this.#network?.publicMcpUrl ?? this.#service.localMcpUrl,
      urlMode: this.#network?.modeLabel ?? "Local",
      exitReason: this.#exitReason,
      networkProvider: this.#config.network.provider,
      configuredPublicUrl: this.#config.network.publicUrl ?? "",
      networkOptions: this.#config.network.options,
      enableShell: this.#config.plugins.shell,
      enabled: this.#config.enabled,
      oauthEnabled: Boolean(this.#config.oauthPassword),
      hasSavedPassword: this.#config.rememberSecrets && Boolean(this.#config.oauthPassword),
      permissionMode: this.#config.permissionMode,
      pluginIds: ["workspace", "shell"],
      tools: this.#registry.listTools().map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.parameters as Readonly<Record<string, unknown>>,
        pluginId: this.#registry.ownerOf(tool.name) ?? "unknown",
      })),
    };
  }

  async start(): Promise<void> {
    if (this.#transition) return this.#transition;
    if (this.#running) return;
    this.#transition = (async () => {
      this.#assertSecuredExposure();
      this.#exitReason = "";
      await this.#service.start();
      try {
        this.#network = await this.#provider.start({ localBaseUrl: this.#service.localBaseUrl, logger: this.#logger });
        this.#running = true;
        this.#logger.log("info", "Pi body ready", {
          workspace: this.#config.workspace,
          mcpUrl: this.#network.publicMcpUrl,
          network: this.#network.modeLabel,
          oauth: Boolean(this.#config.oauthPassword),
          approvalMode: this.#config.permissionMode,
        });
      } catch (error) {
        await this.#provider.stop().catch((stopError) => {
          this.#logger.log("warn", "Tunnel cleanup after failed start failed", { error: String(stopError) });
        });
        await this.#service.stop().catch(() => undefined);
        this.#network = undefined;
        this.#running = false;
        this.#exitReason = error instanceof Error ? error.message : String(error);
        throw error;
      }
    })().finally(() => { this.#transition = undefined; });
    return this.#transition;
  }

  async stop(): Promise<void> {
    if (this.#transition) await this.#transition;
    if (!this.#running) {
      this.approval.resetSession();
      return;
    }
    this.#transition = (async () => {
      // Release pending tool calls before closing the HTTP service; otherwise
      // server.close() can wait on an approval that the stopped UI cannot answer.
      this.approval.resetSession();
      await this.#provider.stop().catch((error) => this.#logger.log("warn", "Tunnel stop failed", { error: String(error) }));
      await this.#service.stop();
      this.#running = false;
      this.#network = undefined;
      this.#logger.log("info", "Pi body stopped");
    })().finally(() => { this.#transition = undefined; });
    return this.#transition;
  }

  async configure(update: RuntimeConfigurationUpdate): Promise<void> {
    if (this.#running) throw new Error("Stop the runtime before changing its configuration");
    const workspace = await stat(update.workspace).catch(() => undefined);
    if (!workspace?.isDirectory()) throw new Error(`Workspace is not a directory: ${update.workspace}`);
    if (!Number.isInteger(update.port) || update.port < 1 || update.port > 65_535) throw new Error(`Invalid MCP port: ${update.port}`);
    const previous = this.#config;
    const mergedOptions = { ...previous.network.options };
    for (const [key, value] of Object.entries(update.network.options)) {
      if (value || !/token|secret|password|key/i.test(key)) mergedOptions[key] = value;
    }
    this.#config = {
      ...previous,
      name: update.name || "Pi MCP Runtime",
      workspace: update.workspace,
      host: update.host,
      port: update.port,
      enabled: update.enabled,
      permissionMode: update.permissionMode,
      oauthPassword: update.oauthPassword || previous.oauthPassword,
      rememberSecrets: update.rememberSecrets,
      network: {
        provider: update.network.provider,
        publicUrl: update.network.publicUrl || undefined,
        options: mergedOptions,
      },
    };
    this.approval.setMode(update.permissionMode);
    await this.#rebuild();
    saveConfig(this.#config, update.rememberSecrets);
    this.#logger.log("info", "Runtime configuration saved", {
      workspace: this.#config.workspace,
      network: this.#config.network.provider,
      permissionMode: this.#config.permissionMode,
    });
  }

  async setEnabled(enabled: boolean): Promise<void> {
    this.#config = { ...this.#config, enabled };
    saveConfig(this.#config, this.#config.rememberSecrets);
  }

  async setPluginEnabled(pluginId: string, enabled: boolean): Promise<void> {
    if (pluginId === "workspace" && !enabled) throw new Error("Workspace Tools is required");
    if (pluginId !== "shell") {
      if (pluginId === "workspace") return;
      throw new Error(`Unknown body plugin: ${pluginId}`);
    }
    if (this.#running) throw new Error("Stop the runtime before changing plugins");
    this.#config = { ...this.#config, plugins: { ...this.#config.plugins, shell: enabled } };
    await this.#rebuild();
    saveConfig(this.#config, this.#config.rememberSecrets);
  }

  async dispose(): Promise<void> {
    await this.stop();
    this.approval.dispose();
    await this.#registry.dispose();
  }

  async #rebuild(): Promise<void> {
    await this.#registry.dispose();
    const parts = this.#createParts();
    this.#registry = parts.registry;
    this.#service = parts.service;
    this.#provider = parts.provider;
  }

  #createParts(): { registry: PluginRegistry; service: McpHttpService; provider: NetworkProvider } {
    const registry = new PluginRegistry({ workspace: this.#config.workspace, logger: this.#logger });
    registry.register(createWorkspacePlugin());
    if (this.#config.plugins.shell) registry.register(createShellPlugin());
    const authorization = new LocalOAuthServer({
      password: this.#config.oauthPassword,
      staticBearerToken: this.#config.authToken,
    });
    const service = new McpHttpService({
      host: this.#config.host,
      port: this.#config.port,
      authorization,
      registry,
      logger: this.#logger,
      executionGate: this.approval,
    });
    return { registry, service, provider: this.#createProvider(service) };
  }

  #createProvider(service: McpHttpService): NetworkProvider {
    const options = this.#config.network.options;
    const executable = options.executable;
    switch (this.#config.network.provider) {
      case "external": return new ExternalNetworkProvider({ publicUrl: this.#config.network.publicUrl ?? service.localBaseUrl });
      case "cloudflare": return new CloudflareNetworkProvider({
        executable: executable || "cloudflared",
        publicUrl: this.#config.network.publicUrl,
        tunnelToken: options.tunnel_token || undefined,
      });
      case "frp": return new FrpNetworkProvider({
        executable: executable || "frpc",
        configFile: options.config_file ?? "",
        publicUrl: this.#config.network.publicUrl ?? "",
      });
      case "ngrok": return new NgrokNetworkProvider({
        executable: executable || "ngrok",
        publicUrl: this.#config.network.publicUrl,
        authToken: options.auth_token || undefined,
      });
      case "tailscale": return new TailscaleNetworkProvider({
        executable: executable || "tailscale",
        publicUrl: this.#config.network.publicUrl ?? "",
      });
    }
  }

  #assertSecuredExposure(): void {
    const loopbackHost = this.#config.host === "localhost"
      || this.#config.host === "::1"
      || /^127\./.test(this.#config.host);
    const localOnly = this.#config.network.provider === "external"
      && loopbackHost
      && (!this.#config.network.publicUrl || /localhost|127\.0\.0\.1|\[::1\]/.test(this.#config.network.publicUrl));
    if (!localOnly && !this.#config.oauthPassword && !this.#config.authToken) {
      throw new Error("Public tunnel exposure requires an OAuth password or MICROMATRIX_AUTH_TOKEN");
    }
  }
}
