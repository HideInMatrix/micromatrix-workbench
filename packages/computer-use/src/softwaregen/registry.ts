import path from "node:path";
import { realpath } from "node:fs/promises";
import { z } from "zod";
import { fail } from "../protocol.js";
import { byteSha256, readBoundedFile, decodeJson } from "./io.js";
import { permissionsSchema } from "./bindings.js";
import { DeclarativeAdapter } from "./runtime.js";

const variable = z.string().max(128).regex(/^[A-Za-z_][A-Za-z0-9_]*$/);
export const extensionRegistrySchema = z.object({
  schema_version: z.literal("1.0"), extensions: z.array(z.object({
    enabled: z.boolean().default(false), bundle: z.string().min(1).max(8192).refine(file => path.isAbsolute(file)),
    sha256: z.string().regex(/^[0-9a-f]{64}$/), permissions: permissionsSchema,
    environment_refs: z.record(variable, variable).default({}), command_environment_refs: z.record(variable, variable).default({}),
  }).strict()).max(32),
}).strict();
/** Explicit local registry only. No workspace discovery, model install tool or generated-code import. */
export async function loadDeclarativeProviders(file: string, environment: Readonly<Record<string, string | undefined>> = process.env, protectedRoots: readonly string[] = []): Promise<DeclarativeAdapter[]> {
  if (!path.isAbsolute(file)) fail("INVALID_REGISTRY", "Registry needs an explicit absolute path");
  const registry = extensionRegistrySchema.parse(decodeJson(await readBoundedFile(file))), providers: DeclarativeAdapter[] = [];
  const roots = await Promise.all([...protectedRoots, ...registry.extensions.filter(e => e.enabled).map(e => e.permissions.filesystem_root)].map(root => realpath(root)));
  const resolve = (refs: Record<string, string>): Record<string, string> => Object.fromEntries(Object.entries(refs).map(([key, source]) => {
    const value = Object.hasOwn(environment, source) ? environment[source] : undefined;
    if (value === undefined) fail("INVALID_BINDINGS", "Selected private environment variable unavailable");
    return [key, value];
  }));
  try {
    for (const entry of registry.extensions) {
      if (!entry.enabled) continue;
      // Configuration/bundles must not be writable using this extension's document tools.
      for (const artifact of [file, entry.bundle, ...entry.permissions.integrity.map(pin => pin.path)]) {
        const canonical = await realpath(artifact);
        if (roots.some(root => { const relative = path.relative(root, canonical); return !relative || relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative); }))
          fail("INVALID_REGISTRY", "Approval artifacts/scripts must be outside every document workspace");
      }
      const bytes = await readBoundedFile(entry.bundle);
      if (byteSha256(bytes) !== entry.sha256) fail("INTEGRITY_FAILED", "Pinned bundle bytes changed; review again before enabling");
      const provider = await DeclarativeAdapter.create(decodeJson(bytes), entry.permissions, {
        environment: resolve(entry.environment_refs), commandEnvironment: resolve(entry.command_environment_refs) });
      if (["desktop", "json", "errors"].includes(provider.id) || providers.some(p => p.id === provider.id)) { await provider.close(); fail("INVALID_REGISTRY", "Duplicate/reserved extension ID"); }
      providers.push(provider);
    }
    return providers;
  } catch (error) { await Promise.all(providers.map(p => p.close())); throw error; }
}
