import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isSea } from "node:sea";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  BrowserAdapter, ComputerUseRuntime, DesktopProxy, JsonDocumentAdapter,
  RemoteDesktopAdapter, VisualDesktopAdapter, createComputerUseServer,
  desktopPlatform, loadDeclarativeProviders, type BrowserConfiguration,
} from "@ouvren/computer-use";

/** Host-owned installation paths; never supplied by the model or saved config.
 * The npm library owns all adapters/protocols, workbench owns desktop packaging. */
export function computerUseHelperPath(): string {
  const platform = desktopPlatform();
  const triple = platform.os === "darwin"
    ? ({ arm64: "aarch64-apple-darwin", x64: "x86_64-apple-darwin" } as Record<string, string>)[process.arch]
    : ({ x64: "x86_64-pc-windows-msvc" } as Record<string, string>)[process.arch];
  if (!triple) throw new Error(`Unsupported Computer Use CPU: ${process.arch}`);
  if (isSea()) {
    const directory = dirname(process.execPath);
    if (platform.os === "darwin") return join(directory, basename(directory) === "MacOS"
      ? "../Helpers/micromatrix Computer Use.app" : "micromatrix Computer Use.app");
    const suffix = basename(process.execPath, ".exe").slice("micromatrix-service".length);
    return join(directory, `micromatrix-computer${suffix.startsWith("-") ? suffix : ""}.exe`);
  }
  const source = fileURLToPath(import.meta.url);
  const binaries = source.endsWith(".cjs")
    ? resolve(dirname(source), "../apps/desktop/binaries")
    : resolve(dirname(source), "../../desktop/binaries");
  return join(binaries, platform.os === "darwin" ? "micromatrix Computer Use.app" : `micromatrix-computer-${triple}.exe`);
}

/** Compose the package's public APIs with the host's explicit helper path. */
export async function startHostedComputerUseMcp(options: {
  workspace: string; allowActions: boolean; version: string;
  asilRegistry?: string; browser?: BrowserConfiguration;
}): Promise<void> {
  const installed = options.asilRegistry
    ? await loadDeclarativeProviders(options.asilRegistry, process.env, [options.workspace]) : [];
  let desktop: DesktopProxy;
  let runtime: ComputerUseRuntime;
  try {
    desktop = new DesktopProxy(desktopPlatform(), computerUseHelperPath());
    runtime = new ComputerUseRuntime([
      desktop, new RemoteDesktopAdapter(desktop), new VisualDesktopAdapter(desktop),
      new JsonDocumentAdapter(options.workspace),
      ...(options.browser ? [new BrowserAdapter(options.browser)] : []), ...installed,
    ], options.allowActions);
  } catch (error) {
    await Promise.all(installed.map(provider => provider.close()));
    throw error;
  }
  const server = createComputerUseServer(runtime, desktop, options.version);
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    try { await runtime.close(); } finally { await server.close(); }
  };
  const exit = () => { void stop().finally(() => process.exit(0)); };
  process.once("SIGTERM", exit);
  process.once("SIGINT", exit);
  process.stdin.once("end", exit);
  try { await server.connect(new StdioServerTransport()); }
  catch (error) { await stop(); throw error; }
}
