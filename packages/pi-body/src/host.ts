import { AsyncLocalStorage } from "node:async_hooks";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import { InMemoryCredentialStore, validateToolArguments, type ToolCall } from "@earendil-works/pi-ai";
import {
  DefaultResourceLoader, ExtensionRunner, ModelRegistry, ModelRuntime,
  SessionManager, SettingsManager, wrapRegisteredTools,
  type InlineExtension, type ResourceLoader, type RegisteredTool,
} from "@earendil-works/pi-coding-agent";
import { PluginRegistry, type PluginContext } from "@micromatrix/plugin-kit";

/** Execution-only official Pi extension host: no Agent/model loop is started. */
export class PiBodyHost {
  readonly registry: PluginRegistry;
  readonly loader: ResourceLoader;
  readonly #runner: ExtensionRunner;
  #closed = false;
  readonly #abort = new AbortController();
  #errors = 0;
  readonly #invocation = new AsyncLocalStorage<{ errors: number }>();
  readonly #toolCache = new WeakMap<RegisteredTool, AgentTool>();

  private constructor(context: PluginContext, loader: ResourceLoader, runner: ExtensionRunner) {
    this.registry = new PluginRegistry(context);
    this.loader = loader;
    this.#runner = runner;
    runner.onError((error) => {
      this.#errors++;
      const invocation = this.#invocation.getStore(); if (invocation) invocation.errors++;
      context.logger.log("error", "Pi extension handler failed", { extension: error.extensionPath, event: error.event });
    });
  }

  static async create(context: PluginContext, agentDir: string, factories: readonly InlineExtension[],
    additionalFactory?: (loader: ResourceLoader) => InlineExtension): Promise<PiBodyHost> {
    let loader: DefaultResourceLoader;
    loader = new DefaultResourceLoader({
      cwd: context.workspace, agentDir, settingsManager: SettingsManager.inMemory(),
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
      systemPrompt: "", appendSystemPrompt: [],
      // Only product-owned factories, never automatically execute .pi/extensions.
      extensionFactories: [...factories, ...(additionalFactory ? [{ name: "skills", factory: async (pi) => {
        const input = additionalFactory(loader);
        await (typeof input === "function" ? input : input.factory)(pi);
      } } satisfies InlineExtension] : [])],
    });
    await loader.reload();
    const loaded = loader.getExtensions();
    if (loaded.errors.length) throw new Error(`Pi extension load failed: ${loaded.errors.map((error) => error.path).join(", ")}`);
    const models = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
      allowModelNetwork: false, refreshOnCreate: false });
    const runner = new ExtensionRunner(loaded.extensions, loaded.runtime, context.workspace,
      SessionManager.inMemory(context.workspace), new ModelRegistry(models));
    const host = new PiBodyHost(context, loader, runner);
    try {
      await runner.emit({ type: "session_start", reason: "startup" });
      if (host.#errors) throw new Error("Pi extension startup failed; check connection configuration and service environment");
      const discovered = await runner.emitResourcesDiscover(context.workspace, "startup");
      if (host.#errors) throw new Error("Pi resource discovery failed");
      loader.extendResources({ skillPaths: discovered.skillPaths.map((entry) => ({ path: entry.path,
        metadata: { source: entry.extensionPath, scope: "temporary", origin: "top-level" } })) });
      const diagnostics = loader.getSkills().diagnostics;
      if (diagnostics.length) throw new Error(`Pi Skill validation failed: ${diagnostics.map((item) => item.message).join("; ")}`);
      // Detect collisions explicitly: Pi's runner otherwise takes the first tool.
      const names = loaded.extensions.flatMap((extension) => [...extension.tools.keys()]);
      if (new Set(names).size !== names.length) throw new Error("Pi extensions registered conflicting tool names");
      for (const extension of loaded.extensions) {
        const tools = [...extension.tools.values()].map(tool => host.#cachedTool(tool));
        const pluginId = extension.path.match(/^<inline:(.+)>$/)?.[1] ?? extension.path;
        host.registry.register({ id: pluginId, displayName: pluginId, createTools: () => tools });
      }
      return host;
    } catch (error) { await host.close(); throw error; }
  }

  #cachedTool(registered: RegisteredTool): AgentTool {
    let tool = this.#toolCache.get(registered);
    if (!tool) { tool = this.#wrap(wrapRegisteredTools([registered], this.#runner)[0]!); this.#toolCache.set(registered, tool); }
    return tool;
  }

  /** Pinned Pi 0.87 has registerTool but no unregister API. Prune the public
   * LoadedExtension tool map in this compatibility boundary, not a second
   * execution registry. Runner.getAllRegisteredTools reads this same map. */
  refreshTools(pluginId: string, activeNames: readonly string[]): void {
    if (this.#closed) return;
    const extension = this.loader.getExtensions().extensions.find(extension => (extension.path.match(/^<inline:(.+)>$/)?.[1] ?? extension.path) === pluginId);
    if (!extension) throw new Error(`Unknown Pi extension: ${pluginId}`);
    const active = new Set(activeNames);
    for (const name of extension.tools.keys()) if (!active.has(name)) extension.tools.delete(name);
    this.registry.replaceTools(pluginId, [...extension.tools.values()].map(tool => this.#cachedTool(tool)));
  }

  #wrap(tool: AgentTool): AgentTool {
    return { ...tool, execute: (callId, params, signal, onUpdate) => this.#invocation.run({ errors: 0 }, async () => {
      if (this.#closed || this.#abort.signal.aborted || signal?.aborted) throw new Error("Pi Runtime stopped or tool call cancelled");
      const executionSignal = signal ? AbortSignal.any([signal, this.#abort.signal]) : this.#abort.signal;
      const args = validateToolArguments(tool, { type: "toolCall", id: callId, name: tool.name, arguments: params as ToolCall["arguments"] });
      const original = JSON.stringify(args);
      const errors = this.#invocation.getStore()!;
      const decision = await this.#runner.emitToolCall({ type: "tool_call", toolName: tool.name, toolCallId: callId, input: args });
      if (errors.errors !== 0) throw new Error("Pi tool_call hook failed");
      if (decision?.block) throw new Error(decision.reason ?? "Blocked by Pi extension");
      // MCP approval already reviewed the original input. Do not allow a hook
      // to substitute a different operation after that approval.
      if (JSON.stringify(args) !== original) throw new Error("Pi extension changed approved arguments; submit a new tool call");
      const result = await tool.execute(callId, args, executionSignal, onUpdate);
      const modified = await this.#runner.emitToolResult({ type: "tool_result", toolName: tool.name, toolCallId: callId,
        input: args, content: result.content, details: result.details, isError: false });
      if (errors.errors !== 0) throw new Error("Pi tool_result hook failed");
      if (modified?.isError) throw new Error("Pi extension marked the tool result as failed");
      return { ...result, ...(modified?.content ? { content: modified.content } : {}),
        ...(modified && "details" in modified ? { details: modified.details } : {}) };
    }) };
  }

  cancel(): void { this.#abort.abort(); }

  async close(): Promise<void> {
    if (this.#closed) return;
    this.#closed = true;
    this.cancel();
    await this.#runner.emit({ type: "session_shutdown", reason: "quit" });
    this.#runner.invalidate("Pi execution Runtime stopped");
    await this.registry.dispose();
  }
}
