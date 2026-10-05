import { constants } from "node:fs";
import { lstat, open, realpath, readdir, writeFile, rename, unlink } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { loadSkills } from "@earendil-works/pi-coding-agent";
import type { SkillSourceConfig } from "@micromatrix/plugin-kit";

const LIMIT = 256_000;
export function digest(document: string): string { return createHash("sha256").update(document).digest("hex"); }
export async function boundedRead(path: string, signal?: AbortSignal): Promise<string> {
  const info = await lstat(path);
  if (!info.isFile() || info.size > LIMIT) throw new Error("Skill file must be a bounded regular file (256 KB)");
  const handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const opened = await handle.stat();
    if (opened.dev !== info.dev || opened.ino !== info.ino || !opened.isFile() || opened.size > LIMIT) throw new Error("Skill file changed while opening");
    // Fixed allocation prevents a growing file from causing unbounded reads.
    const buffer = Buffer.alloc(LIMIT + 1); let length = 0;
    while (length < buffer.length) {
      signal?.throwIfAborted();
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
      if (!bytesRead) break; length += bytesRead;
    }
    if (length > LIMIT) throw new Error("Skill file is too large");
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer.subarray(0, length));
  } finally { await handle.close(); }
}
export async function supportingPath(root: string, path: string): Promise<string> {
  if (!path || path.length > 1024 || /[\\\0]/.test(path) || path.startsWith("/") || path.split("/").some(part => !part || part === "." || part === ".." || part.startsWith(".") || part.includes(":"))) throw new Error("Invalid Skill-relative path");
  const canonical = await realpath(root); let current = canonical;
  for (const part of path.split("/")) {
    current = join(current, part);
    if ((await lstat(current)).isSymbolicLink()) throw new Error("Skill support files must not use symlinks");
  }
  // Re-check ancestors after walking; never accept a canonical escape.
  if (await realpath(current) !== current) throw new Error("Skill support path changed");
  return current;
}
export async function supportFiles(root: string): Promise<readonly { path: string; size: number }[]> {
  const result: { path: string; size: number }[] = []; let visited = 0;
  const walk = async (directory: string, prefix: string, depth: number): Promise<void> => {
    if (depth > 8) throw new Error("Skill support directory is too deep");
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (++visited > 500) throw new Error("Skill support directory exceeds 500 entries");
      if (entry.name.startsWith(".") || entry.name === "node_modules" || entry.isSymbolicLink()) continue;
      const relative = prefix + entry.name;
      if (entry.isDirectory()) await walk(await supportingPath(root, relative), `${relative}/`, depth + 1);
      else if (entry.isFile() && relative !== "SKILL.md") result.push({ path: relative, size: (await lstat(await supportingPath(root, relative))).size });
    }
  };
  await walk(await realpath(root), "", 0);
  return result.sort((a, b) => a.path.localeCompare(b.path));
}
export function discoverSkillFiles(sources: readonly SkillSourceConfig[], workspace: string, enabledOnly = false) {
  const result = loadSkills({ cwd: workspace, agentDir: workspace, skillPaths: sources.filter(source => !enabledOnly || source.enabled).map(source => source.path), includeDefaults: false });
  if (result.diagnostics.length) throw new Error(`Pi Skill validation failed: ${result.diagnostics.map(item => item.message).join("; ")}`);
  return result.skills;
}
export async function readSkillDocument(sources: readonly SkillSourceConfig[], workspace: string, id: string) {
  const skill = discoverSkillFiles(sources, workspace).find(skill => skill.name === id);
  if (!skill) throw new Error("Unknown configured Pi Skill ID");
  const file = resolve(skill.filePath), root = await realpath(dirname(file));
  if (await realpath(file) !== join(root, basename(file))) throw new Error("Skill document must not be a symlink");
  const document = await boundedRead(file);
  return { id, document, revision: digest(document), files: await supportFiles(root) };
}
export async function editSkillDocument(sources: readonly SkillSourceConfig[], workspace: string, id: string, document: string, revision: string): Promise<void> {
  if (!document.trim() || Buffer.byteLength(document) > LIMIT) throw new Error("Invalid or oversized Skill document");
  const skill = discoverSkillFiles(sources, workspace).find(skill => skill.name === id);
  if (!skill) throw new Error("Unknown configured Pi Skill ID");
  const file = resolve(skill.filePath);
  if (digest(await boundedRead(file)) !== revision) throw new Error("Skill changed since it was opened; reload before saving");
  const temporary = join(dirname(file), `.micromatrix-${randomUUID()}.md`);
  try {
    await writeFile(temporary, document, { flag: "wx", mode: 0o600 });
    const validation = loadSkills({ cwd: workspace, agentDir: workspace, skillPaths: [temporary], includeDefaults: false });
    if (validation.diagnostics.length || validation.skills.length !== 1 || validation.skills[0]?.name !== id) throw new Error("Invalid Skill frontmatter or changed name; keep the existing Pi Skill ID");
    if (digest(await boundedRead(file)) !== revision) throw new Error("Skill changed while saving; reload before saving");
    await rename(temporary, file);
  } finally { await unlink(temporary).catch(() => {}); }
}
