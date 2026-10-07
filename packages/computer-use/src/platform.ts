import path from "node:path";
import { fileURLToPath } from "node:url";
import { isSea } from "node:sea";
import { fail } from "./protocol.js";

declare const __MICROMATRIX_RELEASE_BUILD__: boolean;
// Direct TS development defaults to the isolated Dev identity. Bundled builds
// replace this constant; no mutable runtime env or model input selects an ID.
export const computerUseBundleId = typeof __MICROMATRIX_RELEASE_BUILD__ !== "undefined" && __MICROMATRIX_RELEASE_BUILD__
  ? "org.micromatrix.computer-use" : "org.micromatrix.computer-use.dev";

export interface DesktopPlatform {
  readonly os: "darwin" | "win32";
  readonly name: "macos" | "windows";
  readonly source: string;
  readonly operations: readonly string[];
  readonly limitation: string;
}

// Only native access differs. State, action validation, approvals and lifecycle
// remain in one DesktopProxy / ComputerUseRuntime path, not two agents.
const platforms: Record<string, DesktopPlatform> = {
  darwin: { os: "darwin", name: "macos", source: "macos_accessibility",
    operations: ["press", "show_menu", "raise"],
    limitation: "Requires user-granted Accessibility. Secure fields are refused; AX is not full internal software state." },
  win32: { os: "win32", name: "windows", source: "windows_uiautomation",
    operations: ["press", "toggle", "select", "expand", "collapse"],
    limitation: "Requires an unlocked interactive desktop and accessible UI Automation providers. No elevation, UIAccess, secure desktop or password controls." },
};

export function desktopPlatform(os = process.platform): DesktopPlatform {
  return platforms[os] ?? fail("UNSUPPORTED_PLATFORM", "Desktop clients support macOS and Windows only; Linux support is suspended");
}

export function nativeHelperPath(platform = desktopPlatform(), arch = process.arch): string {
  const ext = platform.os === "win32" ? ".exe" : "";
  if (platform.os === "darwin") {
    if (arch !== "arm64" && arch !== "x64") fail("UNSUPPORTED_PLATFORM", `Computer Use native helper does not support ${platform.os}/${arch}`);
    if (isSea()) {
      const directory = path.dirname(process.execPath);
      return path.basename(directory) === "MacOS"
        ? path.join(directory, "../Helpers/micromatrix Computer Use.app")
        : path.join(directory, "micromatrix Computer Use.app");
    }
    if (process.argv[1]?.endsWith("micromatrix-service.cjs")) return path.resolve(path.dirname(process.argv[1]), "../src-tauri/binaries/micromatrix Computer Use.app");
    return fileURLToPath(new URL("../../../src-tauri/binaries/micromatrix Computer Use.app", import.meta.url));
  }
  if (isSea()) {
    const name = path.basename(process.execPath);
    const base = ext && name.endsWith(ext) ? name.slice(0, -ext.length) : name;
    const suffix = base.slice("micromatrix-service".length);
    return path.join(path.dirname(process.execPath), `micromatrix-computer${suffix.startsWith("-") ? suffix : ""}${ext}`);
  }
  const triple = ({ x64: "x86_64-pc-windows-msvc" } as Record<string,string>)[arch];
  if (!triple) fail("UNSUPPORTED_PLATFORM", `Computer Use native helper does not support ${platform.os}/${arch}`);
  const binary = `micromatrix-computer-${triple}${ext}`;
  if (process.argv[1]?.endsWith("micromatrix-service.cjs")) return path.resolve(path.dirname(process.argv[1]), `../src-tauri/binaries/${binary}`);
  return fileURLToPath(new URL(`../../../src-tauri/binaries/${binary}`, import.meta.url));
}
