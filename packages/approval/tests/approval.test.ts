import { describe, expect, it } from "vitest";

import { ApprovalPolicy, type ToolExecutionContext } from "../src/index.js";

function context(sessionId: string): ToolExecutionContext {
  return {
    authentication: "oauth",
    subjectId: `oauth:client-${sessionId}`,
    sessionId,
    clientId: `client-${sessionId}`,
    clientName: `Client ${sessionId}`,
  };
}

describe("ApprovalPolicy", () => {
  it("allows read-only tools and queues workspace writes in safe mode", async () => {
    const policy = new ApprovalPolicy("safe", 1_000);
    await expect(policy.authorize("read", { path: "README.md" })).resolves.toBeUndefined();
    const authorization = policy.authorize("write", {
      path: "secret.txt",
      content: "x",
      apiKey: "hidden",
      nested: { password: "hidden", values: [{ access_token: "hidden" }] },
    });
    const request = policy.requests()[0];
    expect(request).toMatchObject({ toolName: "write", permission: "workspace_write" });
    expect(request?.arguments.apiKey).toBe("[REDACTED]");
    expect(request?.arguments.nested).toEqual({
      password: "[REDACTED]",
      values: [{ access_token: "[REDACTED]" }],
    });
    expect(policy.respond(request?.requestId ?? "", "once")).toBe(true);
    await expect(authorization).resolves.toBeUndefined();
  });

  it("keeps shell approval separate in trusted mode", async () => {
    const policy = new ApprovalPolicy("trusted", 1_000);
    await expect(policy.authorize("write", { path: "ok" })).resolves.toBeUndefined();
    const authorization = policy.authorize("bash", { command: "pwd" });
    const request = policy.requests()[0];
    policy.respond(request?.requestId ?? "", "deny");
    await expect(authorization).rejects.toThrow("approval denied");
  });

  it("scopes session approval to one authenticated client session", async () => {
    const policy = new ApprovalPolicy("safe", 1_000);
    const clientA = context("session-a");
    const clientB = context("session-b");

    const first = policy.authorize("write", { path: "a.txt" }, clientA);
    const request = policy.requests()[0];
    expect(request?.context).toMatchObject({ sessionId: "session-a", clientName: "Client session-a" });
    policy.respond(request?.requestId ?? "", "session");
    await expect(first).resolves.toBeUndefined();
    await expect(policy.authorize("write", { path: "again.txt" }, clientA)).resolves.toBeUndefined();

    const isolated = policy.authorize("write", { path: "b.txt" }, clientB);
    expect(policy.requests()).toHaveLength(1);
    policy.respond(policy.requests()[0]?.requestId ?? "", "deny");
    await expect(isolated).rejects.toThrow("approval denied");
  });

  it("clears client grants and pending calls when the runtime session resets", async () => {
    const policy = new ApprovalPolicy("safe", 1_000);
    const client = context("session-a");
    const granted = policy.authorize("write", { path: "a.txt" }, client);
    policy.respond(policy.requests()[0]?.requestId ?? "", "session");
    await granted;

    const pendingOtherPermission = policy.authorize("bash", { command: "pwd" }, client);
    policy.resetSession();
    await expect(pendingOtherPermission).rejects.toThrow("approval denied");

    const afterReset = policy.authorize("write", { path: "again.txt" }, client);
    expect(policy.requests()).toHaveLength(1);
    policy.respond(policy.requests()[0]?.requestId ?? "", "deny");
    await expect(afterReset).rejects.toThrow("approval denied");
  });
});
