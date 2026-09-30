import { BufferedPluginLogger, ControlPlaneHttpService } from "@micromatrix/control-plane";
import { webAssets } from "@micromatrix/web-assets";

import { loadConfig } from "./config.js";
import { RuntimeSupervisor } from "./runtime.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = new BufferedPluginLogger();
  const runtime = new RuntimeSupervisor(config, logger);
  const control = new ControlPlaneHttpService({
    appName: "MicroMatrix Pi MCP",
    version: "0.1.0",
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
    await control.stop().catch((error) => logger.log("warn", "Control plane stop failed", { error: String(error) }));
    await runtime.dispose().catch((error) => logger.log("warn", "Runtime stop failed", { error: String(error) }));
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

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
