import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

import type { PluginLogger } from "@micromatrix/plugin-kit";

export class ManagedProcess {
  readonly #logger: PluginLogger;
  #child: ChildProcessWithoutNullStreams | undefined;
  #listeners = new Set<(line: string) => void>();

  constructor(logger: PluginLogger) {
    this.#logger = logger;
  }

  get running(): boolean {
    return Boolean(this.#child && this.#child.exitCode === null);
  }

  start(executable: string, args: readonly string[], label: string): void {
    if (this.running) throw new Error(`${label} is already running`);
    this.#child = spawn(executable, [...args], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.#child.once("error", (error) => this.#emit(`${label} spawn error: ${error.message}`));
    this.#read(this.#child.stdout, label);
    this.#read(this.#child.stderr, label);
  }

  waitFor(predicate: (line: string) => boolean, timeoutMs: number, description: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.#listeners.delete(onLine);
        reject(new Error(`Timed out waiting for ${description}`));
      }, timeoutMs);
      const onLine = (line: string) => {
        if (!predicate(line)) return;
        clearTimeout(timeout);
        this.#listeners.delete(onLine);
        resolve(line);
      };
      this.#listeners.add(onLine);
      this.#child?.once("exit", (code) => {
        clearTimeout(timeout);
        this.#listeners.delete(onLine);
        reject(new Error(`Network process exited before ${description}; code=${code ?? "signal"}`));
      });
    });
  }

  async stop(): Promise<void> {
    const child = this.#child;
    this.#child = undefined;
    if (!child || child.exitCode !== null) return;
    child.kill("SIGTERM");
    await Promise.race([
      new Promise<void>((resolve) => child.once("exit", () => resolve())),
      new Promise<void>((resolve) => setTimeout(resolve, 3_000)),
    ]);
    if (child.exitCode === null) child.kill("SIGKILL");
  }

  #read(stream: NodeJS.ReadableStream, label: string): void {
    const lines = createInterface({ input: stream });
    lines.on("line", (line) => {
      const text = line.trim();
      if (!text) return;
      this.#logger.log("debug", `[${label}] ${text}`);
      this.#emit(text);
    });
  }

  #emit(line: string): void {
    for (const listener of this.#listeners) listener(line);
  }
}
