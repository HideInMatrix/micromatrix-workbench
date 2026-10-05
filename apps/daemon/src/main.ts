import { BufferedPluginLogger, ControlPlaneHttpService } from "@micromatrix/control-plane";
import { webAssets } from "@micromatrix/web-assets";
import { startComputerUseMcp } from "@micromatrix/computer-use";
import path from "node:path";

import { loadConfig } from "./config.js";
import { RuntimeSupervisor } from "./runtime.js";
import { APP_VERSION } from "./version.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = new BufferedPluginLogger();
  const runtime = new RuntimeSupervisor(config, logger);
  const control = new ControlPlaneHttpService({
    appName: "micromatrix agent",
    version: APP_VERSION,
    host: config.controlHost,
    port: config.controlPort,
    runtime,
    logs: logger,
    approvals: runtime.approval,
    webAssets,
  });

  let stopping = false;
  async function stop(): Promise<void> {
    if (stopping) return;
    stopping = true;
    await runtime.dispose().catch((error) => logger.log("warn", "Runtime stop failed", { error: String(error) }));
    await control.stop().catch((error) => logger.log("warn", "Control plane stop failed", { error: String(error) }));
  }

  process.once("SIGINT", () => void stop().finally(() => process.exit(0)));
  process.once("SIGTERM", () => void stop().finally(() => process.exit(0)));

  try {
    await control.start();
    logger.log("info", "Desktop control plane listening", { url: control.localBaseUrl });
    // Loading configuration must never execute it. Only start_runtime starts MCP
    // and its tunnel, including when an older config requested auto-start.
  } catch (error) {
    await stop();
    throw error;
  }
}

async function entry(): Promise<void> {
  if (!process.argv.includes("--computer-use-mcp")) return main();
  const index = process.argv.indexOf("--workspace");
  if (index >= 0 && (!process.argv[index+1] || process.argv[index+1]!.startsWith("--"))) throw new Error("--workspace requires a directory");
  await startComputerUseMcp({ workspace: path.resolve(index >= 0 ? process.argv[index+1]! : process.cwd()),
    allowActions: process.argv.includes("--allow-actions"), version: APP_VERSION });
}
void entry().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
