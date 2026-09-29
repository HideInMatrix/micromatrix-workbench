import { describe, expect, it } from "vitest";

import { ApprovalPolicy } from "../src/index.js";

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
});
