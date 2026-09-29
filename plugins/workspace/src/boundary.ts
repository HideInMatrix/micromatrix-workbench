import { constants } from "node:fs";
import {
  access,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  stat,
  writeFile,
} from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import type {
  EditOperations,
  GrepOperations,
  LsOperations,
  ReadOperations,
  WriteOperations,
} from "@earendil-works/pi-coding-agent";

export class WorkspaceBoundaryError extends Error {
  constructor(path: string) {
    super(`Workspace boundary denied path: ${path}`);
    this.name = "WorkspaceBoundaryError";
  }
}

function isWithin(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!isAbsolute(path) && path !== ".." && !path.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`));
}

function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException).code === "ENOENT";
}

async function imageMimeType(path: string): Promise<string | undefined> {
  const file = await open(path, "r");
  try {
    const header = Buffer.alloc(12);
    const { bytesRead } = await file.read(header, 0, header.length, 0);
    if (bytesRead >= 8 && header.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
    if (bytesRead >= 3 && header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff) return "image/jpeg";
    if (bytesRead >= 6 && ["GIF87a", "GIF89a"].includes(header.subarray(0, 6).toString("ascii"))) return "image/gif";
    if (bytesRead >= 12 && header.subarray(0, 4).toString("ascii") === "RIFF" && header.subarray(8, 12).toString("ascii") === "WEBP") return "image/webp";
    if (bytesRead >= 2 && header.subarray(0, 2).toString("ascii") === "BM") return "image/bmp";
    return undefined;
  } finally {
    await file.close();
  }
}

/**
 * Canonical path guard for Pi workspace tools.
 *
 * It enforces both a lexical boundary and the canonical path of the nearest
 * existing ancestor. That blocks absolute-path, `..`, symlink and junction
 * escapes initiated through Workspace Tools. It is not a replacement for an
 * OS sandbox against a separate local process racing filesystem mutations.
 */
export class WorkspaceBoundary {
  readonly root: string;

  constructor(root: string) {
    this.root = resolve(root);
  }

  async existing(path: string): Promise<string> {
    const candidate = this.#lexical(path);
    const [canonicalRoot, canonicalCandidate] = await Promise.all([
      realpath(this.root),
      realpath(candidate),
    ]);
    if (!isWithin(canonicalRoot, canonicalCandidate)) throw new WorkspaceBoundaryError(path);
    return canonicalCandidate;
  }

  async creatable(path: string): Promise<string> {
    const candidate = this.#lexical(path);
    const canonicalRoot = await realpath(this.root);
    let ancestor = candidate;
    for (;;) {
      try {
        await lstat(ancestor);
        break;
      } catch (error) {
        if (!isMissing(error)) throw error;
        const parent = dirname(ancestor);
        if (parent === ancestor) throw error;
        ancestor = parent;
      }
    }
    const canonicalAncestor = await realpath(ancestor);
    if (!isWithin(canonicalRoot, canonicalAncestor)) throw new WorkspaceBoundaryError(path);
    return candidate;
  }

  readOperations(): ReadOperations {
    return {
      access: async (path) => access(await this.existing(path), constants.R_OK),
      readFile: async (path) => readFile(await this.existing(path)),
      detectImageMimeType: async (path) => imageMimeType(await this.existing(path)),
    };
  }

  editOperations(): EditOperations {
    return {
      access: async (path) => access(await this.existing(path), constants.R_OK | constants.W_OK),
      readFile: async (path) => readFile(await this.existing(path)),
      writeFile: async (path, content) => writeFile(await this.existing(path), content, "utf8"),
    };
  }

  writeOperations(): WriteOperations {
    return {
      mkdir: async (path) => {
        const candidate = await this.creatable(path);
        await mkdir(candidate, { recursive: true });
        await this.existing(candidate);
      },
      writeFile: async (path, content) => {
        const candidate = await this.creatable(path);
        await writeFile(candidate, content, "utf8");
        await this.existing(candidate);
      },
    };
  }

  grepOperations(): GrepOperations {
    return {
      isDirectory: async (path) => (await stat(await this.existing(path))).isDirectory(),
      readFile: async (path) => readFile(await this.existing(path), "utf8"),
    };
  }

  lsOperations(): LsOperations {
    return {
      exists: async (path) => {
        try {
          await this.existing(path);
          return true;
        } catch (error) {
          if (isMissing(error)) return false;
          throw error;
        }
      },
      stat: async (path) => stat(await this.existing(path)),
      readdir: async (path) => readdir(await this.existing(path)),
    };
  }

  #lexical(path: string): string {
    const candidate = resolve(this.root, path);
    if (!isWithin(this.root, candidate)) throw new WorkspaceBoundaryError(path);
    return candidate;
  }
}
