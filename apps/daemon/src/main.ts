import { stat } from "node:fs/promises";

import { McpHttpService } from "@micromatrix/mcp-server";
import {
  CloudflareNetworkProvider,
  ExternalNetworkProvider,
  type NetworkProvider,
} from "@micromatrix/network";
import { ConsolePluginLogger, PluginRegistry } from "@micromatrix/plugin-kit";
import { createShellPlugin } from "@micromatrix/plugin-shell";
import { createWorkspacePlugin } from "@micromatrix/plugin-workspace";

import { loadConfig } from "./config.js";

const config = loadConfig();
const workspaceStat = await stat(config.workspace).catch(() => undefined);
if (!workspaceStat?.isDirectory()) throw new Error(`Workspace is not a directory: ${config.workspace}`);

const logger = new ConsolePluginLogger();
const registry = new PluginRegistry({ workspace: config.workspace, logger });
registry.register(createWorkspacePlugin());
if (config.enableShell) registry.register(createShellPlugin());

const service = new McpHttpService({
  host: config.host,
  port: config.port,
  authToken: config.authToken,
  registry,
  logger,
});

function createProvider(): NetworkProvider {
  if (config.network.provider === "cloudflare") {
    if (!config.authToken) {
      throw new Error("Cloudflare exposure requires MICROMATRIX_AUTH_TOKEN");
    }
    return new CloudflareNetworkProvider({
      executable: config.network.executable,
      publicUrl: config.network.publicUrl,
      tunnelToken: config.network.tunnelToken,
    });
  }
  return new ExternalNetworkProvider({ publicUrl: config.network.publicUrl ?? service.localBaseUrl });
}

const provider = createProvider();
let stopping = false;

async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  await provider.stop().catch((error) => logger.log("warn", "Tunnel stop failed", { error: String(error) }));
  await service.stop().catch((error) => logger.log("warn", "MCP stop failed", { error: String(error) }));
  await registry.dispose();
}

process.once("SIGINT", () => void stop().finally(() => process.exit(0)));
process.once("SIGTERM", () => void stop().finally(() => process.exit(0)));

try {
  await service.start();
  const network = await provider.start({ localBaseUrl: service.localBaseUrl, logger });
  logger.log("info", "Pi body ready", {
    workspace: config.workspace,
    mcpUrl: network.publicMcpUrl,
    network: network.modeLabel,
  });
} catch (error) {
  await stop();
  throw error;
}
