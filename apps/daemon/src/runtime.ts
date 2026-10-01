import { stat } from "node:fs/promises";

import { ApprovalPolicy } from "@micromatrix/approval";
import type { RuntimeConfigurationUpdate, RuntimeControl, RuntimeSnapshot, SecretUpdate } from "@micromatrix/control-plane";
import { McpHttpService } from "@micromatrix/mcp-server";
import {
  CloudflareNetworkProvider,
  ExternalNetworkProvider,
  FrpNetworkProvider,
  NgrokNetworkProvider,
  TailscaleNetworkProvider,
  parseCloudflareProtocol,
  type NetworkProvider,
  type NetworkProviderResult,
} from "@micromatrix/network";
import { LocalOAuthServer } from "@micromatrix/oauth";
import { PluginRegistry, type PluginLogger } from "@micromatrix/plugin-kit";
import { createShellPlugin } from "@micromatrix/plugin-shell";
import { createWorkspacePlugin } from "@micromatrix/plugin-workspace";

import { saveConfig, type DaemonConfig } from "./config.js";
import { defaultCloudflaredExecutable } from "./tunnel-executable.js";
import { APP_VERSION } from "./version.js";

export class RuntimeSupervisor implements RuntimeControl {
  #config: DaemonConfig;
  readonly #logger: PluginLogger;
  readonly approval: ApprovalPolicy;
  #registry: PluginRegistry;
  #service: McpHttpService | undefined;
  #provider: NetworkProvider | undefined;
  #network: NetworkProviderResult | undefined;
  #running = false;
  #transition: Promise<void> | undefined;
  #failureCleanup: Promise<void> | undefined;
  #exitReason = "";

  constructor(config: DaemonConfig, logger: PluginLogger) {
    this.#config = config;
    this.#logger = logger;
    this.approval = new ApprovalPolicy(config.permissionMode);
    // Do not construct providers or bind MCP while loading an unfinished config.
    this.#registry = this.#createRegistry(config);
  }

  snapshot(): RuntimeSnapshot {
    return {
      runtimeId: "default",
      name: this.#config.name,
      workspace: this.#config.workspace,
      host: this.#config.host,
      port: this.#config.port,
      running: this.#running,
      publicMcpUrl: this.#running ? (this.#network?.publicMcpUrl ?? "") : "",
      urlMode: this.#network?.modeLabel ?? "Local",
      exitReason: this.#exitReason,
      networkProvider: this.#config.network.provider,
      configuredPublicUrl: this.#config.network.publicUrl ?? "",
      networkOptions: this.#config.network.options,
      enableShell: this.#config.plugins.shell,
      oauthEnabled: Boolean(this.#config.oauthPassword),
      rememberSecrets: this.#config.rememberSecrets,
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
    return this.#exclusive(async () => {
      if (this.#failureCleanup) await this.#failureCleanup;
      if (this.#running) return;
      this.#exitReason = "";
      try {
        const workspace = await stat(this.#config.workspace).catch(() => undefined);
        if (!workspace?.isDirectory()) throw new Error(`Workspace is not a directory: ${this.#config.workspace}`);
        this.#assertSecuredExposure();
        const service = this.#service ?? this.#createService(this.#config, this.#registry);
        const provider = this.#provider ?? this.#createProvider(this.#config, service);
        this.#service = service;
        this.#provider = provider;
        await provider.preflight?.();
        await service.start();
        let startingFailure: Error | undefined;
        let starting = true;
        this.#network = await provider.start({
          localBaseUrl: service.localBaseUrl,
          logger: this.#logger,
          onUnexpectedExit: (error) => {
            if (starting) startingFailure = error;
            else this.#handleNetworkFailure(error);
          },
        });
        if (startingFailure) throw startingFailure;
        this.#running = true;
        starting = false;
        this.#logger.log("info", "Pi body ready", {
          workspace: this.#config.workspace,
          mcpUrl: this.#network.publicMcpUrl,
          network: this.#network.modeLabel,
          oauth: Boolean(this.#config.oauthPassword),
          approvalMode: this.#config.permissionMode,
        });
      } catch (error) {
        await this.#provider?.stop().catch((stopError) => {
          this.#logger.log("warn", "Tunnel cleanup after failed start failed", { error: String(stopError) });
        });
        await this.#service?.stop().catch(() => undefined);
        this.#provider = undefined;
        this.#service = undefined;
        this.#network = undefined;
        this.#running = false;
        this.#exitReason = error instanceof Error ? error.message : String(error);
        throw error;
      }
    });
  }

  async stop(): Promise<void> {
    return this.#exclusive(async () => {
      if (this.#failureCleanup) await this.#failureCleanup;
      if (!this.#running) {
        this.approval.resetSession();
        return;
      }
      // Release pending tool calls before closing the HTTP service; otherwise
      // server.close() can wait on an approval that the stopped UI cannot answer.
      this.approval.resetSession();
      await this.#provider?.stop().catch((error) => this.#logger.log("warn", "Tunnel stop failed", { error: String(error) }));
      await this.#service?.stop();
      this.#provider = undefined;
      this.#service = undefined;
      this.#running = false;
      this.#network = undefined;
      this.#logger.log("info", "Pi body stopped");
    });
  }

  async configure(update: RuntimeConfigurationUpdate): Promise<void> {
    return this.#exclusive(async () => {
      if (this.#running) throw new Error("Stop the runtime before changing its configuration");
      if (this.#failureCleanup) await this.#failureCleanup;
      const workspace = await stat(update.workspace).catch(() => undefined);
      if (!workspace?.isDirectory()) throw new Error(`Workspace is not a directory: ${update.workspace}`);
      if (!Number.isInteger(update.port) || update.port < 1 || update.port > 65_535) throw new Error(`Invalid MCP port: ${update.port}`);
      if (update.port === this.#config.controlPort) throw new Error("MCP port must differ from the control port");
      const previous = this.#config;
      const mergedOptions = { ...previous.network.options };
      for (const [key, value] of Object.entries(update.network.options)) {
        mergedOptions[key] = value;
      }
      for (const [key, secretUpdate] of Object.entries(update.network.secretUpdates)) {
        const value = applySecretUpdate(mergedOptions[key], secretUpdate);
        if (value === undefined) delete mergedOptions[key];
        else mergedOptions[key] = value;
      }
      const candidate: DaemonConfig = {
        ...previous,
        name: update.name || "Pi MCP Runtime",
        workspace: update.workspace,
        host: update.host,
        port: update.port,
        permissionMode: update.permissionMode,
        oauthPassword: applySecretUpdate(previous.oauthPassword, update.oauthPassword),
        rememberSecrets: update.rememberSecrets,
        network: {
          provider: update.network.provider,
          publicUrl: update.network.publicUrl || undefined,
          options: mergedOptions,
        },
      };
      await this.#commitConfiguration(candidate);
      this.#logger.log("info", "Runtime configuration saved", {
        workspace: this.#config.workspace,
        network: this.#config.network.provider,
        permissionMode: this.#config.permissionMode,
      });
    });
  }

  async setPluginEnabled(pluginId: string, enabled: boolean): Promise<void> {
    return this.#exclusive(async () => {
      if (pluginId === "workspace" && !enabled) throw new Error("Workspace Tools is required");
      if (pluginId !== "shell") {
        if (pluginId === "workspace") return;
        throw new Error(`Unknown body plugin: ${pluginId}`);
      }
      if (this.#running) throw new Error("Stop the runtime before changing plugins");
      if (this.#failureCleanup) await this.#failureCleanup;
      await this.#commitConfiguration({ ...this.#config, plugins: { ...this.#config.plugins, shell: enabled } });
    });
  }

  async dispose(): Promise<void> {
    await this.stop();
    this.approval.dispose();
    await this.#registry.dispose();
  }

  #exclusive(action: () => Promise<void>): Promise<void> {
    const transition = (this.#transition ?? Promise.resolve()).catch(() => undefined).then(action);
    this.#transition = transition;
    const clear = () => { if (this.#transition === transition) this.#transition = undefined; };
    void transition.then(clear, clear);
    return transition;
  }

  async #commitConfiguration(config: DaemonConfig): Promise<void> {
    const registry = this.#createRegistry(config);
    let service: McpHttpService;
    let provider: NetworkProvider;
    try {
      service = this.#createService(config, registry);
      provider = this.#createProvider(config, service);
      // Disk failure must leave the live snapshot and old tools unchanged, too.
      saveConfig(config, config.rememberSecrets);
    } catch (error) {
      await registry.dispose();
      throw error;
    }
    const previous = this.#registry;
    this.#config = config;
    this.#registry = registry;
    this.#service = service;
    this.#provider = provider;
    this.approval.setMode(config.permissionMode);
    this.#exitReason = "";
    await previous.dispose().catch((error) => {
      this.#logger.log("warn", "Old plugin registry cleanup failed", { error: String(error) });
    });
  }

  #handleNetworkFailure(error: Error): void {
    if (!this.#running || this.#failureCleanup) return;
    this.#running = false;
    this.#network = undefined;
    this.#exitReason = `Network provider stopped unexpectedly: ${error.message}`;
    this.approval.resetSession();
    this.#logger.log("error", this.#exitReason);
    this.#failureCleanup = (async () => {
      await this.#provider?.stop().catch((stopError) => {
        this.#logger.log("warn", "Tunnel cleanup after unexpected exit failed", { error: String(stopError) });
      });
      await this.#service?.stop().catch((stopError) => {
        this.#logger.log("warn", "MCP cleanup after unexpected tunnel exit failed", { error: String(stopError) });
      });
      this.#provider = undefined;
      this.#service = undefined;
    })().finally(() => { this.#failureCleanup = undefined; });
  }

  #createRegistry(config: DaemonConfig): PluginRegistry {
    const registry = new PluginRegistry({ workspace: config.workspace, logger: this.#logger });
    registry.register(createWorkspacePlugin());
    if (config.plugins.shell) registry.register(createShellPlugin());
    return registry;
  }

  #createService(config: DaemonConfig, registry: PluginRegistry): McpHttpService {
    const authorization = new LocalOAuthServer({
      password: config.oauthPassword,
      staticBearerToken: config.authToken,
    });
    return new McpHttpService({
      host: config.host,
      port: config.port,
      authorization,
      registry,
      logger: this.#logger,
      executionGate: this.approval,
      serverInfo: { name: "micromatrix agent", version: APP_VERSION },
    });
  }

  #createProvider(config: DaemonConfig, service: McpHttpService): NetworkProvider {
    const options = config.network.options;
    const executable = options.executable;
    switch (config.network.provider) {
      case "external": return new ExternalNetworkProvider({ publicUrl: config.network.publicUrl ?? service.localBaseUrl });
      case "cloudflare": return new CloudflareNetworkProvider({
        executable: executable || defaultCloudflaredExecutable(),
        publicUrl: config.network.publicUrl,
        tunnelToken: options.tunnel_token || undefined,
        protocol: parseCloudflareProtocol(options.protocol),
      });
      case "frp": return new FrpNetworkProvider({
        executable: executable || "frpc",
        configFile: options.config_file ?? "",
        publicUrl: config.network.publicUrl ?? "",
      });
      case "ngrok": return new NgrokNetworkProvider({
        executable: executable || "ngrok",
        publicUrl: config.network.publicUrl,
        authToken: options.auth_token || undefined,
      });
      case "tailscale": return new TailscaleNetworkProvider({
        executable: executable || "tailscale",
        publicUrl: config.network.publicUrl ?? "",
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

export function applySecretUpdate(current: string | undefined, update: SecretUpdate): string | undefined {
  switch (update.action) {
    case "unchanged": return current;
    case "clear": return undefined;
    case "set": return update.value;
  }
}
