import { realpath, mkdir, writeFile, unlink } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { loadSkills, type ExtensionFactory, type ResourceLoader } from "@earendil-works/pi-coding-agent";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import type { SkillSourceConfig } from "@micromatrix/plugin-kit";

import { boundedRead, supportingPath, supportFiles } from "./files.js";
export { readSkillDocument, editSkillDocument, discoverSkillFiles } from "./files.js";

export interface LoadedSkill {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly filePath: string;
  readonly disableModelInvocation: boolean;
}

export function loadedSkills(loader: ResourceLoader): readonly LoadedSkill[] {
  return loader.getSkills().skills.map((skill) => ({ id: skill.name, name: skill.name, description: skill.description,
    filePath: skill.filePath, disableModelInvocation: skill.disableModelInvocation }));
}

export async function validateSkillSource(path: string, workspace: string): Promise<void> {
  if (!isAbsolute(path)) throw new Error("Skill import path must be absolute");
  const result = loadSkills({ cwd: workspace, agentDir: workspace, skillPaths: [path], includeDefaults: false });
  if (!result.skills.length || result.diagnostics.length) throw new Error(`Invalid skill source: ${result.diagnostics.map((item) => item.message).join("; ") || "No SKILL.md found"}`);
}

export async function createSkillFile(root: string, id: string, description: string, instructions: string): Promise<string> {
  if (!/^[a-z][a-z0-9-]{0,23}$/.test(id) || id.includes("--") || id.endsWith("-") || !description.trim() || description.length > 1024 || !instructions.trim() || instructions.length > 256_000) throw new Error("Invalid Skill name, description or instructions");
  const document = `---\nname: ${id}\ndescription: ${JSON.stringify(description.trim())}\n---\n\n${instructions}\n`;
  if (Buffer.byteLength(document) > 256_000) throw new Error("Skill document is too large");
  const folder = join(root, id);
  await mkdir(folder, { recursive: true, mode: 0o700 });
  const path = join(folder, "SKILL.md");
  await writeFile(path, document, { flag: "wx", mode: 0o600 });
  return path;
}

export async function removeCreatedSkill(path: string): Promise<void> { await unlink(path); }

export function createSkillsExtension(sources: readonly SkillSourceConfig[], loader: ResourceLoader): ExtensionFactory {
  return (pi) => {
    const registeredFiles = new Map<string, string>();
    pi.on("resources_discover", async (_event, ctx) => {
      const skillPaths = sources.filter((source) => source.enabled).map((source) => source.path);
      const discovery = loadSkills({ cwd: ctx.cwd, agentDir: ctx.cwd, skillPaths, includeDefaults: false });
      registeredFiles.clear();
      for (const skill of discovery.skills) registeredFiles.set(resolve(skill.filePath), await realpath(skill.filePath));
      return { skillPaths };
    });
    pi.registerTool({
      name: "skills_list", label: "Pi Skills", description: "List instructions loaded by Pi. Skills are documents, not executable tools. Use skills_read with an ID to read the full instructions.",
      parameters: { type: "object", properties: {}, additionalProperties: false } as AgentTool["parameters"],
      async execute() {
        const skills = loadedSkills(loader).filter((skill) => !skill.disableModelInvocation).map(({ filePath: _path, ...summary }) => summary);
        return { content: [{ type: "text", text: JSON.stringify(skills) }], details: { skills } };
      },
    });
    pi.registerTool({
      name: "skills_read", label: "Read Pi Skill", description: "Read a skill by its exact Pi skill ID. Returns instructions without executing scripts or granting tool permissions.",
      parameters: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: false } as AgentTool["parameters"],
      async execute(_callId, params, signal) {
        const id = params && typeof params === "object" ? Reflect.get(params as object, "id") : undefined;
        const skill = loadedSkills(loader).find((skill) => skill.id === id);
        if (!skill) throw new Error("Unknown Pi Skill ID");
        const path = resolve(skill.filePath);
        // No arbitrary read path in the tool API. Reject replaced symlinks and
        // files that grew beyond the bounded instruction-document size.
        const canonical = await realpath(path);
        if (canonical !== registeredFiles.get(path)) throw new Error("Skill file path changed; reload Runtime");
        const instructions = await boundedRead(path, signal);
        return { content: [{ type: "text", text: instructions }], details: { id: skill.id } };
      },
    });
    pi.registerTool({
      name: "skills_files", label: "Pi Skill support files", description: "List supporting files within a loaded Pi Skill. Never executes scripts.",
      parameters: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: false } as AgentTool["parameters"],
      async execute(_callId, params) {
        const root = await skillRoot(Reflect.get(params as object, "id"));
        const files = await supportFiles(root);
        return { content: [{ type: "text", text: JSON.stringify(files) }], details: { files } };
      },
    });
    pi.registerTool({
      name: "skills_file_read", label: "Read Pi Skill support file", description: "Read a UTF-8 supporting file by Skill ID and relative path (256 KB max); no execution, absolute paths, traversal or symlinks.",
      parameters: { type: "object", properties: { id: { type: "string" }, path: { type: "string" } }, required: ["id", "path"], additionalProperties: false } as AgentTool["parameters"],
      async execute(_callId, params, signal) {
        const root = await skillRoot(Reflect.get(params as object, "id"));
        const file = await supportingPath(root, String(Reflect.get(params as object, "path")));
        return { content: [{ type: "text", text: await boundedRead(file, signal) }], details: {} };
      },
    });
    async function skillRoot(id: unknown): Promise<string> {
      const skill = loadedSkills(loader).find(skill => skill.id === id);
      if (!skill) throw new Error("Unknown Pi Skill ID");
      const path = resolve(skill.filePath);
      if (await realpath(path) !== registeredFiles.get(path)) throw new Error("Skill file path changed; reload Runtime");
      return dirname(registeredFiles.get(path)!);
    }
  };
}
