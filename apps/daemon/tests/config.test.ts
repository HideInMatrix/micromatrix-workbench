import { describe, expect, it } from "vitest";

import { loadConfig } from "../src/config.js";

describe("daemon configuration", () => {
  it("loads the new environment contract", () => {
    const config = loadConfig({
      MICROMATRIX_WORKSPACE: "/tmp",
      MICROMATRIX_PORT: "9000",
      MICROMATRIX_NETWORK_PROVIDER: "cloudflare",
      MICROMATRIX_PUBLIC_URL: "https://body.example.com",
      MICROMATRIX_TUNNEL_TOKEN: "secret",
      MICROMATRIX_ENABLE_SHELL: "true",
      MICROMATRIX_CONFIG_FILE: "/tmp/micromatrix-test-missing.json",
    });

    expect(config).toMatchObject({
      workspace: "/tmp",
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
      AGENT_RUNTIME_WORKSPACE: "/tmp",
      AGENT_RUNTIME_NETWORK_PROVIDER: "external",
      AGENT_RUNTIME_SERVER_URL: "https://legacy.example.com",
      MICROMATRIX_CONFIG_FILE: "/tmp/micromatrix-test-missing.json",
    });
    expect(config.network).toMatchObject({
      provider: "external",
      publicUrl: "https://legacy.example.com",
    });
  });
});
