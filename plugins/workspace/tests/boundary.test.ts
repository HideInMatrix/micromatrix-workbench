import { access, mkdtemp, mkdir, readFile, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { createWorkspacePlugin, WorkspaceBoundary } from "../src/index.js";

const cleanup: string[] = [];

async function fixture() {
  const parent = await mkdtemp(join(tmpdir(), "micromatrix-boundary-"));
  const workspace = join(parent, "workspace");
  const outside = join(parent, "outside");
  await Promise.all([mkdir(workspace), mkdir(outside)]);
  await writeFile(join(workspace, "inside.txt"), "inside", "utf8");
  await writeFile(join(outside, "secret.txt"), "secret", "utf8");
  await symlink(join(workspace, "inside.txt"), join(workspace, "inside-link"), "file");
  await symlink(outside, join(workspace, "escape"), "dir");
  cleanup.push(parent);
  return { workspace, outside };
}

afterEach(async () => {
  await Promise.all(cleanup.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("WorkspaceBoundary", () => {
  it("allows paths whose canonical target stays inside the workspace", async () => {
    const { workspace } = await fixture();
    const boundary = new WorkspaceBoundary(workspace);
    await expect(boundary.existing("inside.txt")).resolves.toBe(await realpath(join(workspace, "inside.txt")));
    await expect(boundary.existing(join(workspace, "inside.txt"))).resolves.toBe(await realpath(join(workspace, "inside.txt")));
    await expect(boundary.existing("inside-link")).resolves.toBe(await realpath(join(workspace, "inside.txt")));
    await expect(boundary.creatable("nested/new.txt")).resolves.toBe(join(workspace, "nested/new.txt"));
  });

  it("rejects lexical traversal and absolute paths outside the workspace", async () => {
    const { workspace, outside } = await fixture();
    const boundary = new WorkspaceBoundary(workspace);
    await expect(boundary.existing(join("..", basename(outside), "secret.txt"))).rejects.toThrow("Workspace boundary denied");
    await expect(boundary.existing(join(outside, "secret.txt"))).rejects.toThrow("Workspace boundary denied");
  });

  it("rejects existing and new targets reached through an escaping symlink", async () => {
    const { workspace } = await fixture();
    const boundary = new WorkspaceBoundary(workspace);
    await expect(boundary.existing("escape/secret.txt")).rejects.toThrow("Workspace boundary denied");
    await expect(boundary.creatable("escape/new.txt")).rejects.toThrow("Workspace boundary denied");
  });
});

describe("workspace BodyPlugin", () => {
  it("applies the boundary to every Pi workspace tool", async () => {
    const { workspace, outside } = await fixture();
    const plugin = createWorkspacePlugin();
    const tools = plugin.createTools({ workspace, logger: { log() {} } });
    const outsideFile = join(outside, "secret.txt");
    const calls = [
      ["read", { path: outsideFile }],
      ["grep", { path: outsideFile, pattern: "secret" }],
      ["find", { path: outside, pattern: "*" }],
      ["ls", { path: outside }],
      ["edit", { path: outsideFile, edits: [{ oldText: "secret", newText: "leaked" }] }],
    ] as const;
    for (const [name, arguments_] of calls) {
      const tool = tools.find((candidate) => candidate.name === name);
      expect(tool, `${name} tool`).toBeDefined();
      await expect(tool!.execute(`${name}-outside`, arguments_)).rejects.toThrow();
    }

    const write = tools.find((tool) => tool.name === "write");
    expect(write).toBeDefined();
    await expect(write!.execute("write-outside", { path: "escape/new.txt", content: "blocked" })).rejects.toThrow("Workspace boundary denied");
    await expect(access(join(outside, "new.txt"))).rejects.toThrow();
    await expect(write!.execute("write-inside", { path: "nested/ok.txt", content: "ok" })).resolves.toMatchObject({
      content: [{ type: "text" }],
    });
    await expect(readFile(join(workspace, "nested/ok.txt"), "utf8")).resolves.toBe("ok");
  });
});
