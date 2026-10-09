import { stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

import { ApprovalPolicy } from "@micromatrix/approval";
import type { RuntimeConfigurationUpdate, RuntimeControl, RuntimeSnapshot, SecretUpdate, BuiltinComputerUseStatus, ComputerUsePermissionStatus } from "@micromatrix/control-plane";
import { browserConfiguration, DesktopProxy, desktopPlatform, nativeHelperPath } from "@micromatrix/computer-use";
import { McpHttpService } from "@micromatrix/mcp-server";
import {
  NetworkHealthMonitor, PublicRouteError, probePublicService, waitForPublicService, normalizeBaseUrl,
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
import { PluginRegistry, parseExtensions, type ExtensionConfiguration, type McpConnectionConfig, type PluginLogger } from "@micromatrix/plugin-kit";
import { PiBodyHost, createPiBodyExtension } from "@micromatrix/pi-body";
import { createMcpExtension, McpConnection, McpAuthStore, type McpExtensionController, type McpOptions } from "@micromatrix/plugin-mcp";
import { createSkillsExtension, createSkillFile, loadedSkills, removeCreatedSkill, validateSkillSource, readSkillDocument, editSkillDocument, discoverSkillFiles } from "@micromatrix/plugin-skills";
import { createShellPlugin } from "@micromatrix/plugin-shell";
import { createWorkspacePlugin } from "@micromatrix/plugin-workspace";

import { saveConfig, type DaemonConfig } from "./config.js";
import { defaultCloudflaredExecutable } from "./tunnel-executable.js";
import { APP_VERSION } from "./version.js";
import { builtinComputerUseConfiguration, computerUseConnection } from "./builtin-computer-use.js";

export class RuntimeSupervisor implements RuntimeControl {
  computerUseConnection(): McpConnectionConfig {
    return computerUseConnection(this.#config.workspace, true, false, this.#config.computerUse);
  }
  #computerPermission: ComputerUsePermissionStatus | null = null;
  #computerPermissionCheckedAt = 0;
  #computerPermissionError = "";
  computerUseStatus(): BuiltinComputerUseStatus {
    const supported = process.platform === "darwin" || process.platform === "win32";
    let helperPath = "";
    try { if (supported) helperPath = nativeHelperPath(); } catch { /* Unsupported CPU. */ }
    const conflict = parseExtensions(this.#config.extensions).mcp.some(connection => connection.id === "computer_use");
    return { enabled: this.#config.computerUse?.enabled ?? false, allowActions: this.#config.computerUse?.allowActions ?? true,
      supported: supported && Boolean(helperPath), available: Boolean(helperPath && existsSync(helperPath)),
      platform: supported ? desktopPlatform().name : process.platform, helperPath,
      running: this.#running, connected: this.#running && this.#mcpHealth.get("computer_use")?.status === "connected",
      permission: this.#computerPermission, checkedAt: this.#computerPermissionCheckedAt,
      error: this.#computerPermissionError, conflict, ...(this.#config.computerUse?.browser ? {browser: this.#config.computerUse.browser} : {}) };
  }
  async setComputerUseEnabled(enabled: boolean): Promise<void> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      if (this.#failureCleanup) await this.#failureCleanup;
      const status = this.computerUseStatus();
      if (enabled && (!status.supported || !status.available)) throw new Error("Computer Use native helper unavailable; install a complete macOS or Windows desktop build");
      if (enabled && status.conflict) throw new Error("Rename the custom MCP ID computer_use before enabling the built-in plugin");
      // A user's enable action opts into control, still guarded by existing approvals/TCC.
      // Saving a builtin must not validate/start an unfinished Tunnel configuration.
      await this.#saveExtensions(parseExtensions(this.#config.extensions), { ...this.#config.computerUse, enabled, allowActions: enabled || status.allowActions });
      this.#computerPermission = null; this.#computerPermissionCheckedAt = 0; this.#computerPermissionError = "";
    });
  }
  async configureComputerUseBrowser(value: unknown): Promise<void> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      if (this.#failureCleanup) await this.#failureCleanup;
      const parsed = value === null ? undefined : browserConfiguration.safeParse(value);
      if (parsed && !parsed.success) {
        const field = parsed.error.issues[0]?.path[0];
        throw new Error(field === "endpoint" ? "浏览器连接地址须为本机 WebSocket，例如 ws://127.0.0.1:9222/devtools/browser/ID"
          : field === "allowedOrigins" ? "允许的网站须为 HTTP(S) origin，例如 https://example.com；不含额外路径，最多 32 个"
          : "浏览器配置只接受连接地址和允许的网站列表");
      }
      const browser = parsed?.data;
      const { browser: _previous, ...configuration } = this.#config.computerUse ?? {enabled: false, allowActions: true};
      // Parse and persist only: no browser connection, profile discovery,
      // download, permission prompt or Runtime/Tunnel startup on Save.
      await this.#saveExtensions(parseExtensions(this.#config.extensions), {...configuration, ...(browser ? {browser} : {})});
    });
  }
  async checkComputerUsePermissions(request = false): Promise<BuiltinComputerUseStatus> {
    return this.#exclusive(() => this.#checkComputerUsePermissions(request));
  }
  async #checkComputerUsePermissions(request: boolean): Promise<BuiltinComputerUseStatus> {
    const status = this.computerUseStatus();
    if (!status.enabled) throw new Error("Enable Computer Use before checking its system permission");
    if (!status.supported || !status.available) throw new Error("Computer Use native helper unavailable");
    if (request && (!status.allowActions || status.platform !== "macos")) throw new Error("Explicit Accessibility requests require enabled macOS control");
    const desktop = new DesktopProxy();
    try {
      // Check only the fixed helper's trust/desktop status; never read app contents.
      const result = await desktop.permissions(request) as Record<string, unknown>;
      if (status.platform === "macos" ? typeof result.accessibility !== "boolean" : typeof result.interactive_desktop !== "boolean") throw new Error("Invalid native permission response");
      this.#computerPermission = { platform: status.platform as "macos" | "windows", helperPath: status.helperPath,
        ...(status.platform === "macos" ? { accessibility: result.accessibility as boolean,
          ...(typeof result.bundle_id === "string" ? { bundleId: result.bundle_id } : {}),
          signingMode: result.signing_mode === "certificate" ? "certificate" as const : "ad-hoc" as const, screenRecording:result.screen_recording===true }
          : { interactiveDesktop: result.interactive_desktop as boolean, elevated: result.elevated === true }),
        promptRequested: request, requiresScreenRecording: false };
      this.#computerPermissionCheckedAt = Date.now(); this.#computerPermissionError = "";
      return this.computerUseStatus();
    } catch (error) {
      this.#computerPermission = null; this.#computerPermissionCheckedAt = Date.now();
      this.#computerPermissionError = error instanceof Error ? error.message : String(error);
      throw error;
    } finally { await desktop.close(); }
  }
  #config: DaemonConfig;
  readonly #logger: PluginLogger;
  readonly approval: ApprovalPolicy;
  #registry: PluginRegistry;
  #host: PiBodyHost | undefined;
  #service: McpHttpService | undefined;
  #provider: NetworkProvider | undefined;
  #network: NetworkProviderResult | undefined;
  #networkHealth: NetworkHealthMonitor | undefined;
  #running = false;
  #startingAbort: AbortController | undefined;
  #testingMcp: McpConnection | undefined;
  #transition: Promise<void> | undefined;
  #failureCleanup: Promise<void> | undefined;
  #exitReason = "";
  #networkWarning = "";
  readonly #mcpAuth: McpAuthStore;
  readonly #mcpControllers = new Map<string, McpExtensionController>();
  readonly #mcpCatalogs = new Map<string, readonly string[]>();
  readonly #mcpHealth = new Map<string, { status: string; message: string; discoveredAt: number }>();

  constructor(config: DaemonConfig, logger: PluginLogger) {
    const builtin = builtinComputerUseConfiguration(config.computerUse, parseExtensions(config.extensions));
    this.#config = { ...config, computerUse: builtin.configuration, extensions: builtin.extensions };
    this.#logger = logger;
    this.#mcpAuth = new McpAuthStore(`${config.configFile}.mcp-credentials.json`, config.rememberSecrets);
    this.approval = new ApprovalPolicy(config.permissionMode, 120_000, (event) => {
      const level = event.outcome === "queued" || event.outcome === "allowed" ? "info" : "warn";
      this.#logger.log(level, `Tool approval: ${event.outcome}`, { ...event });
    });
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
      publicMcpUrl: this.#running && !this.#networkWarning ? (this.#network?.publicMcpUrl ?? "") : "",
      networkWarning: this.#networkWarning,
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
      extensions: parseExtensions(this.#config.extensions),
      skills: this.#host ? loadedSkills(this.#host.loader).map(({ filePath: _path, ...skill }) => skill) : [],
      extensionHostActive: Boolean(this.#host),
      mcpStatus: Object.fromEntries(parseExtensions(this.#config.extensions).mcp.map(connection => {
        const authentication = this.#mcpAuth.summary(connection);
        const health = this.#mcpHealth.get(connection.id) ?? { status: "stopped", message: "", discoveredAt: 0 };
        return [connection.id, { ...authentication, ...health, message: health.message || authentication.message }];
      })),
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
      this.#networkWarning = "";
      const startup = new AbortController(); this.#startingAbort = startup;
      try {
        const workspace = await stat(this.#config.workspace).catch(() => undefined);
        if (!workspace?.isDirectory()) throw new Error(`Workspace is not a directory: ${this.#config.workspace}`);
        this.#assertSecuredExposure();
        const preview = this.#service ?? this.#createService(this.#config, this.#registry);
        const provider = this.#provider ?? this.#createProvider(this.#config, preview);
        this.#provider = provider;
        await provider.preflight?.();
        startup.signal.throwIfAborted();
        const context = { workspace: this.#config.workspace, logger: this.#logger };
        const extensions = parseExtensions(this.#config.extensions);
        const builtin = this.computerUseStatus();
        if (builtin.enabled && builtin.conflict) throw new Error("Custom MCP ID computer_use conflicts with the built-in plugin");
        if (builtin.enabled) await this.#checkComputerUsePermissions(false); // Never prompt on Start.
        startup.signal.throwIfAborted();
        const connections = [...extensions.mcp, ...(builtin.enabled ? [computerUseConnection(this.#config.workspace, true, builtin.allowActions, this.#config.computerUse)] : [])];
        const plugins = [createWorkspacePlugin(), ...(this.#config.plugins.shell ? [createShellPlugin()] : [])];
        this.#host = await PiBodyHost.create(context, join(dirname(this.#config.configFile), "pi"), [
          ...plugins.map((plugin) => ({ name: plugin.id, factory: createPiBodyExtension([plugin], context) })),
          ...connections.filter((connection) => connection.enabled).map((connection) => ({
            name: `mcp:${connection.id}`, factory: createMcpExtension(connection, this.#mcpOptions(connection), names => {
              this.#mcpCatalogs.set(connection.id, names);
              this.#host?.refreshTools(`mcp:${connection.id}`, names);
            }, controller => this.#mcpControllers.set(connection.id, controller)),
          })),
        ], extensions.skills.some((source) => source.enabled)
          ? (loader) => ({ name: "skills", factory: createSkillsExtension(extensions.skills, loader) }) : undefined);
        for (const [id, names] of this.#mcpCatalogs) this.#host.refreshTools(`mcp:${id}`, names);
        await this.#registry.dispose();
        this.#registry = this.#host.registry;
        this.#registry.subscribe(() => this.approval.resetSession());
        const service = this.#createService(this.#config, this.#registry);
        this.#service = service;
        startup.signal.throwIfAborted();
        if (this.#config.network.publicUrl) service.setPublicBaseUrl(normalizeBaseUrl(this.#config.network.publicUrl));
        await service.start();
        startup.signal.throwIfAborted();
        let startingFailure: Error | undefined;
        let starting = true;
        this.#network = await provider.start({
          signal: startup.signal,
          localBaseUrl: service.localBaseUrl,
          logger: this.#logger,
          onUnexpectedExit: (error) => {
            if (starting) { startingFailure = error; startup.abort(error); }
            else this.#handleNetworkFailure(error);
          },
        });
        startup.signal.throwIfAborted();
        if (startingFailure) throw startingFailure;
        service.setPublicBaseUrl(this.#network.publicBaseUrl);
        try { await waitForPublicService(this.#network.publicBaseUrl, service.instanceId, startup.signal); }
        catch (error) { throw startingFailure ?? new Error("Tunnel address is not ready or does not reach this MCP instance", { cause: error }); }
        if (startingFailure) throw startingFailure;
        startup.signal.throwIfAborted();
        const publicBaseUrl = this.#network.publicBaseUrl;
        this.#networkHealth = new NetworkHealthMonitor(signal => probePublicService(publicBaseUrl, service.instanceId, signal), () => {}, 15000, {
          keepRunningOnFailure: true,
          onProbeResult: ({ ok, failures, error }) => {
            if (!this.#running) return;
            if (ok) {
              if (this.#networkWarning) this.#logger.log("info", "Public MCP route recovered; Runtime remained running");
              this.#networkWarning = "";
              return;
            }
            const code = error instanceof PublicRouteError ? error.code : "unknown";
            if (failures <= 3 || failures % 20 === 0) this.#logger.log(failures >= 3 ? "warn" : "debug", "Public MCP health probe failed", { failures, code, message: error?.message });
            if (failures >= 3) this.#networkWarning = `公网探活连续失败，本地 Runtime 和 Tunnel 保持运行，正在等待恢复。${error?.message ?? ""}`;
          },
        });
        this.#networkHealth.start();
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
        await this.#networkHealth?.stop(); this.#networkHealth = undefined;
        await this.#provider?.stop().catch((stopError) => {
          this.#logger.log("warn", "Tunnel cleanup after failed start failed", { error: String(stopError) });
        });
        await this.#unloadHost();
        await this.#service?.stop().catch(() => undefined);
        this.#provider = undefined;
        this.#service = undefined;
        this.#network = undefined;
        this.#running = false;
        this.#exitReason = error instanceof Error ? error.message : String(error);
        throw error;
      } finally { if (this.#startingAbort === startup) this.#startingAbort = undefined; }
    });
  }

  async stop(): Promise<void> {
    // Stop must interrupt a hanging MCP handshake before waiting for the serial
    // lifecycle queue; desktop exit cannot leave an initializing npx tree alive.
    this.#mcpAuth.cancelPending();
    this.#startingAbort?.abort();
    const healthCleanup = this.#networkHealth?.stop(); this.#networkHealth = undefined;
    const earlyCleanup = Promise.all([
      ...[...this.#mcpControllers.values()].map(controller => controller.close().catch(() => {})),
      this.#testingMcp?.close().catch(() => {}),
      ...(this.#startingAbort ? [this.#provider?.stop().catch(() => {})] : []),
    ]);
    return this.#exclusive(async () => {
      await healthCleanup;
      await earlyCleanup;
      if (this.#failureCleanup) await this.#failureCleanup;
      this.#mcpAuth.cancelPending();
      if (!this.#running) {
        this.approval.resetSession();
        return;
      }
      // Release pending tool calls before closing the HTTP service; otherwise
      // server.close() can wait on an approval that the stopped UI cannot answer.
      this.approval.resetSession();
      await this.#unloadHost();
      await this.#provider?.stop().catch((error) => this.#logger.log("warn", "Tunnel stop failed", { error: String(error) }));
      await this.#service?.stop();
      this.#provider = undefined;
      this.#service = undefined;
      this.#running = false;
      this.#network = undefined;
      this.#networkWarning = "";
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
    this.#mcpAuth.close();
    this.approval.dispose();
    await this.#registry.dispose();
  }

  async configureExtensions(value: ExtensionConfiguration): Promise<void> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      if (this.#failureCleanup) await this.#failureCleanup;
      const extensions = parseExtensions(value);
      const builtin = builtinComputerUseConfiguration(undefined, extensions);
      if (builtin.extensions.mcp.some(connection => connection.id === "computer_use")) throw new Error("computer_use is reserved for the built-in plugin; use a different custom MCP ID");
      for (const source of extensions.skills) if (source.enabled) await validateSkillSource(source.path, this.#config.workspace);
      discoverSkillFiles(extensions.skills, this.#config.workspace, true);
      // Compatibility for older desktop presets; migrate, do not duplicate a child.
      await this.#saveExtensions(builtin.extensions, builtin.extensions.mcp.length !== extensions.mcp.length ? builtin.configuration : this.#config.computerUse);
    });
  }

  async createSkill(id: string, description: string, instructions: string): Promise<void> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      if (this.#failureCleanup) await this.#failureCleanup;
      const previous = parseExtensions(this.#config.extensions);
      if (previous.skills.some((source) => source.id === id)) throw new Error("Skill ID already exists");
      const path = await createSkillFile(join(dirname(this.#config.configFile), "skills"), id, description, instructions);
      try {
        await validateSkillSource(path, this.#config.workspace);
        await this.#saveExtensions(parseExtensions({ ...previous, skills: [...previous.skills, { id, path, enabled: true }] }));
      } catch (error) { await removeCreatedSkill(path); throw error; }
    });
  }

  async testMcpConnection(value: McpConnectionConfig): Promise<{ tools: readonly string[] }> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      const config = parseExtensions({ mcp: [value] }).mcp[0]!;
      if (config.auth === "oauth" && this.#mcpAuth.summary(config).oauth === "pending") throw new Error("Complete or cancel OAuth login before testing");
      const connection = new McpConnection(config, this.#mcpOptions(config));
      this.#testingMcp = connection;
      try {
        const tools = (await connection.connect(this.#config.workspace)).map(tool => tool.name);
        this.#mcpHealth.set(config.id, { status: "tested", message: "Test passed; temporary connection closed", discoveredAt: Date.now() });
        return { tools };
      } catch (error) {
        this.#mcpHealth.set(config.id, { status: "test_failed", message: "Connection test failed; check credentials, login and executable path", discoveredAt: 0 });
        throw error;
      } finally { await connection.close(); if (this.#testingMcp === connection) this.#testingMcp = undefined; }
    });
  }

  #mcpOptions(config: McpConnectionConfig): McpOptions {
    return { values: this.#mcpAuth.values(config), ...(this.#startingAbort ? { signal: this.#startingAbort.signal } : {}), ...(config.transport === "http" ? { fetch: this.#mcpAuth.fetchMcp } : {}),
      ...(config.auth === "oauth" ? { authProvider: this.#mcpAuth.provider(config) } : {}),
      onStatus: (status, message) => this.#mcpHealth.set(config.id, { status, message, discoveredAt: status === "connected" ? Date.now() : this.#mcpHealth.get(config.id)?.discoveredAt ?? 0 }) };
  }
  #connection(id: string): McpConnectionConfig {
    const config = parseExtensions(this.#config.extensions).mcp.find(connection => connection.id === id);
    if (!config) throw new Error("Unknown configured MCP ID"); return config;
  }
  async setMcpCredentials(id: string, updates: unknown): Promise<void> {
    return this.#exclusive(async () => { this.#assertExtensionsEditable(); this.#mcpAuth.update(this.#connection(id), updates); });
  }
  async beginMcpLogin(id: string): Promise<{ url: string }> {
    return this.#exclusive(async () => { this.#assertExtensionsEditable(); return this.#mcpAuth.begin(this.#connection(id)); });
  }
  async cancelMcpLogin(id: string): Promise<void> { this.#mcpAuth.cancel(id); }
  async logoutMcp(id: string): Promise<void> {
    return this.#exclusive(async () => { this.#assertExtensionsEditable(); this.#mcpAuth.logout(this.#connection(id)); });
  }
  async refreshMcpTools(id: string): Promise<void> {
    return this.#exclusive(async () => {
      if (!this.#running) throw new Error("Start Runtime before refreshing MCP tools");
      const controller = this.#mcpControllers.get(id); if (!controller) throw new Error("MCP is not enabled");
      await controller.refresh();
    });
  }
  async skillDocuments(): Promise<readonly { id: string; description: string }[]> {
    return discoverSkillFiles(parseExtensions(this.#config.extensions).skills, this.#config.workspace).map(skill => ({ id: skill.name, description: skill.description }));
  }
  async readSkill(id: string): Promise<Awaited<ReturnType<typeof readSkillDocument>>> {
    return readSkillDocument(parseExtensions(this.#config.extensions).skills, this.#config.workspace, id);
  }
  async editSkill(id: string, document: string, revision: string): Promise<void> {
    return this.#exclusive(async () => {
      this.#assertExtensionsEditable();
      await editSkillDocument(parseExtensions(this.#config.extensions).skills, this.#config.workspace, id, document, revision);
    });
  }

  #assertExtensionsEditable(): void {
    if (this.#running) throw new Error("Stop Runtime before changing extensions or testing connections");
  }

  async #saveExtensions(extensions: ExtensionConfiguration, computerUse = this.#config.computerUse ?? { enabled: false, allowActions: true }): Promise<void> {
    const candidate = { ...this.#config, extensions, computerUse };
    // Save without constructing providers or connecting external servers.
    saveConfig(candidate, candidate.rememberSecrets);
    try { this.#mcpAuth.prune(extensions.mcp); }
    catch (error) { saveConfig(this.#config, this.#config.rememberSecrets); throw error; }
    this.#config = candidate;
  }

  async #unloadHost(): Promise<void> {
    const host = this.#host;
    this.#host = undefined;
    host?.cancel();
    // Close owned transports concurrently before Pi's sequential shutdown hooks.
    await Promise.all([...this.#mcpControllers.values()].map(controller => controller.close().catch(() => {})));
    this.#mcpControllers.clear(); this.#mcpCatalogs.clear(); this.#mcpHealth.clear();
    if (!host) return;
    await host.close().catch(() => this.#logger.log("warn", "Pi extension shutdown failed"));
    this.#registry = this.#createRegistry(this.#config);
  }

  #exclusive<T>(action: () => Promise<T>): Promise<T> {
    const result = (this.#transition ?? Promise.resolve()).catch(() => undefined).then(action);
    const transition = result.then(() => undefined);
    this.#transition = transition;
    const clear = () => { if (this.#transition === transition) this.#transition = undefined; };
    void transition.then(clear, clear);
    return result;
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
      try { this.#mcpAuth.setRemember(config.rememberSecrets); }
      catch (error) { saveConfig(this.#config, this.#config.rememberSecrets); throw error; }
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
    this.#networkWarning = "";
    this.#exitReason = `Network provider stopped unexpectedly: ${error.message}`;
    this.approval.resetSession();
    this.#logger.log("error", this.#exitReason);
    this.#failureCleanup = (async () => {
      await this.#networkHealth?.stop(); this.#networkHealth = undefined;
      await this.#provider?.stop().catch((stopError) => {
        this.#logger.log("warn", "Tunnel cleanup after unexpected exit failed", { error: String(stopError) });
      });
      await this.#unloadHost();
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
      && (!this.#config.network.publicUrl || (() => { const u = new URL(this.#config.network.publicUrl!); return u.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname); })());
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
