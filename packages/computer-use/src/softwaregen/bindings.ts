import path from "node:path";
import { realpath, stat } from "node:fs/promises";
import { z } from "zod";
import { fail } from "../protocol.js";
import type { ExtensionBundle } from "./models.js";
import { executableName, shellExecutable } from "./audit.js";
import { checkedBaseUrl, byteSha256, readBoundedFile } from "./io.js";
import { resolveEnvironment } from "./templates.js";

const absolute = z.string().min(1).max(8192).refine(value => path.isAbsolute(value) && !value.includes("\0"));
export const permissionsSchema = z.object({
  filesystem_root: absolute,
  base_url: z.string().max(8192).optional(),
  executables: z.record(z.string().max(128), z.object({ path: absolute, prefix: z.array(z.string().max(8192)).max(64).default([]) }).strict()).default({}),
  integrity: z.array(z.object({ path: absolute, sha256: z.string().regex(/^[0-9a-f]{64}$/) }).strict()).max(128).default([]),
}).strict();
export type RuntimePermissions = z.input<typeof permissionsSchema>;
export interface PrivateBindings { environment?: Readonly<Record<string, string>>; commandEnvironment?: Readonly<Record<string, string>> }
export interface ApprovedBindings {
  root: string; baseUrl?: string; headers: Record<string, string>; environment: Readonly<Record<string, string>>;
  commandEnvironment: Readonly<Record<string, string>>; permissions: z.output<typeof permissionsSchema>;
  executablePaths: Record<string, string>;
}
const interpreter = /^(?:node|python(?:[0-9.]+)?|ruby|perl|php|deno|osascript)(?:\.exe)?$/i;
export async function approveBindings(bundle: ExtensionBundle, input: RuntimePermissions, privateBindings: PrivateBindings = {}): Promise<ApprovedBindings> {
  const permissions = permissionsSchema.parse(input), root = await realpath(permissions.filesystem_root);
  if (!(await stat(root)).isDirectory()) fail("INVALID_BINDINGS", "Approved root must be a directory");
  const declaredRoot = bundle.profile.runtime.filesystem_root;
  if (declaredRoot !== "." && (!path.isAbsolute(declaredRoot) || await realpath(declaredRoot) !== root)) fail("INVALID_BINDINGS", "Profile filesystem root differs from approved binding");
  const environment = Object.freeze({ ...privateBindings.environment });
  const resolvedBase = bundle.profile.runtime.base_url_env ? environment[bundle.profile.runtime.base_url_env] || bundle.profile.runtime.base_url : bundle.profile.runtime.base_url;
  let baseUrl: string | undefined;
  if (bundle.plan.observation_views.some(v => v.probe.transport === "http_json") || bundle.plan.operations.some(o => o.request.transport === "http_json")) {
    if (!permissions.base_url || !resolvedBase) fail("INVALID_BINDINGS", "HTTP requires a separate approved base URL");
    const url = checkedBaseUrl(resolvedBase), approved = checkedBaseUrl(permissions.base_url);
    if (url.href !== approved.href || !bundle.profile.runtime.allowed_hosts.includes(url.hostname.replace(/^\[|\]$/g, ""))) fail("INVALID_BINDINGS", "Resolved URL differs from approved host/origin/path binding");
    baseUrl = url.href;
  }
  const headers = Object.fromEntries(Object.entries(bundle.profile.runtime.headers).map(([key, value]) => [key, resolveEnvironment(value, environment)]));
  try { new Headers(headers); } catch { fail("INVALID_BINDINGS", "Invalid private headers; values omitted"); }
  const executablePaths: Record<string, string> = Object.create(null) as Record<string, string>;
  const commands = [...bundle.plan.observation_views.flatMap(v => v.probe.transport === "command_json" ? [v.probe.argv] : []),
    ...bundle.plan.operations.flatMap(o => o.request.transport === "command_json" ? [o.request.argv] : [])];
  for (const argv of commands) {
    const name = executableName(argv[0]!), binding = Object.hasOwn(permissions.executables, name) ? permissions.executables[name]! : undefined;
    if (!binding || shellExecutable.test(name) || /\.(?:cmd|bat|ps1)$/i.test(binding.path)) fail("INVALID_BINDINGS", "Command has no approved non-shell executable binding");
    if (path.isAbsolute(argv[0]!) && argv[0] !== binding.path) fail("INVALID_BINDINGS", "Command path differs from approved executable");
    const executable = await realpath(binding.path);
    if (!(await stat(executable)).isFile() || shellExecutable.test(executableName(executable))) fail("INVALID_BINDINGS", "Bound executable must be a regular non-shell program");
    if (!binding.prefix.every((arg, i) => argv[i + 1] === arg && !arg.includes("${"))) fail("INVALID_BINDINGS", "Command does not match approved fixed prefix");
    // General interpreters need a pinned reviewed script; never silently execute mutable workspace code.
    if (interpreter.test(name) || interpreter.test(executableName(executable))) {
      const script = binding.prefix[0];
      if (!script || script.startsWith("-") || !path.isAbsolute(script) || !permissions.integrity.some(p => p.path === script)) fail("INVALID_BINDINGS", "Interpreter requires absolute reviewed script prefix and integrity pin");
    }
    executablePaths[name] = executable;
  }
  const commandEnvironment = { ...Object.fromEntries(["SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"].flatMap(key => process.env[key] ? [[key, process.env[key]!]] : [])), ...privateBindings.commandEnvironment };
  if (Object.keys(commandEnvironment).some(key => /^(?:NODE_OPTIONS|NODE_PATH|PYTHONPATH|PYTHONSTARTUP|LD_.*|DYLD_.*)$/i.test(key))) fail("INVALID_BINDINGS", "Runtime injection environment variables forbidden");
  const result: ApprovedBindings = { root, headers, environment, commandEnvironment: Object.freeze(commandEnvironment), permissions, executablePaths,
    ...(baseUrl ? { baseUrl } : {}) };
  await verifyIntegrity(result);
  return result;
}
export async function verifyIntegrity(bindings: ApprovedBindings): Promise<void> {
  for (const pin of bindings.permissions.integrity) {
    if (byteSha256(await readBoundedFile(pin.path)) !== pin.sha256) fail("INTEGRITY_FAILED", "Reviewed support file changed; approve a new artifact before executing");
  }
}
