import { randomUUID } from "node:crypto";

export type ApprovalMode = "safe" | "trusted" | "dangerous";
export type ApprovalDecision = "deny" | "once" | "session";

export interface ToolExecutionContext {
  readonly authentication: "anonymous" | "static_bearer" | "oauth";
  readonly subjectId: string;
  readonly sessionId: string;
  readonly clientId?: string;
  readonly clientName?: string;
}

export interface ToolApprovalRequest {
  readonly requestId: string;
  readonly toolName: string;
  readonly permission: "workspace_write" | "shell_execute" | "open_world";
  readonly reason: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly context: ToolExecutionContext;
  readonly createdAt: number;
  readonly expiresAt: number;
}

export interface ToolExecutionGate {
  authorize(
    toolName: string,
    args: Readonly<Record<string, unknown>>,
    context?: ToolExecutionContext,
    signal?: AbortSignal,
  ): Promise<void>;
}

type ApprovalOutcome = "allowed" | "denied" | "timed_out" | "cancelled" | "stopped";

export interface ApprovalEvent {
  readonly requestId: string;
  readonly toolName: string;
  readonly permission: ToolApprovalRequest["permission"];
  readonly sessionId: string;
  readonly outcome: "queued" | ApprovalOutcome;
}

interface PendingApproval {
  readonly request: ToolApprovalRequest;
  readonly settle: (outcome: ApprovalOutcome) => void;
}

const READ_ONLY = new Set(["read", "grep", "find", "ls"]);
const WRITES = new Set(["edit", "write"]);
const LOCAL_CONTEXT: ToolExecutionContext = Object.freeze({
  authentication: "anonymous",
  subjectId: "local-anonymous",
  sessionId: "local-anonymous",
  clientName: "Local client",
});

export class ApprovalPolicy implements ToolExecutionGate {
  #mode: ApprovalMode;
  readonly #timeoutMs: number;
  readonly #pending = new Map<string, PendingApproval>();
  readonly #sessionAllowed = new Set<string>();
  readonly #onEvent: ((event: ApprovalEvent) => void) | undefined;

  constructor(mode: ApprovalMode = "safe", timeoutMs = 120_000, onEvent?: (event: ApprovalEvent) => void) {
    this.#mode = mode;
    this.#timeoutMs = timeoutMs;
    this.#onEvent = onEvent;
  }

  get mode(): ApprovalMode {
    return this.#mode;
  }

  setMode(mode: ApprovalMode): void {
    this.#mode = mode;
    this.#sessionAllowed.clear();
  }

  requests(): readonly ToolApprovalRequest[] {
    return [...this.#pending.values()].map(({ request }) => request);
  }

  respond(requestId: string, decision: ApprovalDecision): boolean {
    if (!["deny", "once", "session"].includes(decision)) return false;
    const pending = this.#pending.get(requestId);
    if (!pending) return false;
    if (Date.now() / 1_000 >= pending.request.expiresAt) {
      pending.settle("timed_out");
      return false;
    }
    if (decision === "session") {
      this.#sessionAllowed.add(this.#sessionKey(pending.request.context, pending.request.permission));
    }
    pending.settle(decision === "deny" ? "denied" : "allowed");
    return true;
  }

  async authorize(
    toolName: string,
    args: Readonly<Record<string, unknown>>,
    context: ToolExecutionContext = LOCAL_CONTEXT,
    signal?: AbortSignal,
  ): Promise<void> {
    if (signal?.aborted) throw new Error(`Tool approval cancelled: ${toolName} (client disconnected or cancelled)`);
    const permission = this.#permission(toolName);
    if (!permission || this.#allowed(permission, context)) return;
    const request: ToolApprovalRequest = {
      requestId: randomUUID(),
      toolName,
      permission,
      reason: permission === "shell_execute"
        ? "模型请求执行本地 shell 命令。"
        : permission === "workspace_write"
          ? "模型请求修改 Workspace 文件。"
          : "模型请求执行可访问外部环境的操作。",
      arguments: this.#redact(args),
      context: Object.freeze({ ...context }),
      createdAt: Date.now() / 1_000,
      expiresAt: (Date.now() + this.#timeoutMs) / 1_000,
    };
    const outcome = await new Promise<ApprovalOutcome>((resolve) => {
      const settle = (result: ApprovalOutcome) => {
        if (!this.#pending.has(request.requestId)) return;
        this.#pending.delete(request.requestId);
        clearTimeout(timer);
        signal?.removeEventListener("abort", cancel);
        this.#event(request, result);
        resolve(result);
      };
      const cancel = () => settle("cancelled");
      const timer = setTimeout(() => settle("timed_out"), this.#timeoutMs);
      this.#pending.set(request.requestId, { request, settle });
      signal?.addEventListener("abort", cancel, { once: true });
      this.#event(request, "queued");
    });
    if (outcome === "allowed") return;
    const details: Record<Exclude<ApprovalOutcome, "allowed">, string> = {
      denied: "denied by the user",
      timed_out: "timed out waiting for desktop approval; open the desktop app and retry",
      cancelled: "cancelled by the client or connection; retry and keep the call open",
      stopped: "cancelled because the runtime stopped",
    };
    throw new Error(`Tool approval ${details[outcome]}: ${toolName}`);
  }

  dispose(): void {
    this.resetSession();
  }

  resetSession(): void {
    for (const pending of this.#pending.values()) {
      pending.settle("stopped");
    }
    this.#pending.clear();
    this.#sessionAllowed.clear();
  }

  #event(request: ToolApprovalRequest, outcome: ApprovalEvent["outcome"]): void {
    // Audit metadata only: never send command contents or secrets to logs.
    this.#onEvent?.({ requestId: request.requestId, toolName: request.toolName,
      permission: request.permission, sessionId: request.context.sessionId, outcome });
  }

  #permission(toolName: string): ToolApprovalRequest["permission"] | undefined {
    if (READ_ONLY.has(toolName)) return undefined;
    if (WRITES.has(toolName)) return "workspace_write";
    if (toolName === "bash") return "shell_execute";
    return "open_world";
  }

  #allowed(permission: ToolApprovalRequest["permission"], context: ToolExecutionContext): boolean {
    if (this.#mode === "dangerous") return true;
    if (this.#sessionAllowed.has(this.#sessionKey(context, permission))) return true;
    return this.#mode === "trusted" && permission === "workspace_write";
  }

  #sessionKey(context: ToolExecutionContext, permission: ToolApprovalRequest["permission"]): string {
    return `${context.sessionId}\u0000${permission}`;
  }

  #redact(args: Readonly<Record<string, unknown>>): Readonly<Record<string, unknown>> {
    return this.#redactValue(args) as Readonly<Record<string, unknown>>;
  }

  #redactValue(value: unknown): unknown {
    if (Array.isArray(value)) return value.map((item) => this.#redactValue(item));
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key,
      /token|password|secret|key/i.test(key) ? "[REDACTED]" : this.#redactValue(item),
    ]));
  }
}
