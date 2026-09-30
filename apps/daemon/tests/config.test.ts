import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { loadConfig } from "../src/config.js";

describe("daemon configuration", () => {
  let workspace: string;
  beforeEach(() => { workspace = mkdtempSync(join(tmpdir(), "micromatrix-config-test-")); });
  afterEach(() => { rmSync(workspace, { recursive: true, force: true }); });

  it("loads the new environment contract", () => {
    const config = loadConfig({
      MICROMATRIX_WORKSPACE: workspace,
      MICROMATRIX_PORT: "9000",
      MICROMATRIX_NETWORK_PROVIDER: "cloudflare",
      MICROMATRIX_PUBLIC_URL: "https://body.example.com",
      MICROMATRIX_TUNNEL_TOKEN: "secret",
      MICROMATRIX_ENABLE_SHELL: "true",
      MICROMATRIX_CONFIG_FILE: join(workspace, "runtime.json"),
    });

    expect(config).toMatchObject({
      workspace: resolve(workspace),
      port: 9000,
      plugins: { shell: true },
      network: {
        provider: "cloudflare",
        publicUrl: "https://body.example.com",
        options: { tunnel_token: "secret" },
      },
    });
  });

  it("keeps master tunnel variable aliases during transition", () => {
    const config = loadConfig({
      AGENT_RUNTIME_WORKSPACE: workspace,
      AGENT_RUNTIME_NETWORK_PROVIDER: "external",
      AGENT_RUNTIME_SERVER_URL: "https://legacy.example.com",
      MICROMATRIX_CONFIG_FILE: join(workspace, "runtime.json"),
    });
    expect(config.workspace).toBe(resolve(workspace));
    expect(config.network).toMatchObject({
      provider: "external",
      publicUrl: "https://legacy.example.com",
    });
  });
});
