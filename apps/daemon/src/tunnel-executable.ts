import path from "node:path";
import { isSea } from "node:sea";

/** Packaged apps must not depend on a GUI launcher's PATH or a system install. */
export function defaultCloudflaredExecutable(options: {
  packaged?: boolean;
  serviceExecutable?: string;
  platform?: NodeJS.Platform;
} = {}): string {
  if (!(options.packaged ?? isSea())) return "cloudflared";
  const executable = options.serviceExecutable ?? process.execPath;
  const windows = (options.platform ?? process.platform) === "win32";
  const paths = windows ? path.win32 : path.posix;
  const extension = windows ? ".exe" : "";
  const name = paths.basename(executable);
  // Before Tauri bundling, both sidecars retain their target suffix.
  const suffix = name.slice("micromatrix-service".length).replace(/\.exe$/i, "");
  return paths.join(paths.dirname(executable), `cloudflared${suffix.startsWith("-") ? suffix : ""}${extension}`);
}
