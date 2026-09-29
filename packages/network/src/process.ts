import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

import type { PluginLogger } from "@micromatrix/plugin-kit";

export class ManagedProcess {
  readonly #logger: PluginLogger;
  #child: ChildProcessWithoutNullStreams | undefined;
  #listeners = new Set<(line: string) => void>();
  #error: Error | undefined;
  #errorListeners = new Set<(error: Error) => void>();

  constructor(logger: PluginLogger) {
    this.#logger = logger;
  }

  get running(): boolean {
    return Boolean(this.#child && this.#child.exitCode === null);
  }

  start(executable: string, args: readonly string[], label: string): void {
    if (this.running) throw new Error(`${label} is already running`);
    this.#error = undefined;
    this.#child = spawn(executable, [...args], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.#child.once("error", (error) => {
      const failure = new Error(`${label} spawn error: ${error.message}`, { cause: error });
      this.#error = failure;
      this.#logger.log("error", failure.message);
      for (const listener of this.#errorListeners) listener(failure);
    });
    this.#read(this.#child.stdout, label);
    this.#read(this.#child.stderr, label);
  }

  waitFor(predicate: (line: string) => boolean, timeoutMs: number, description: string): Promise<string> {
    if (this.#error) return Promise.reject(this.#error);
    return new Promise((resolve, reject) => {
      const child = this.#child;
      const cleanup = () => {
        clearTimeout(timeout);
        this.#listeners.delete(onLine);
        this.#errorListeners.delete(onError);
        child?.off("exit", onExit);
      };
      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error(`Timed out waiting for ${description}`));
      }, timeoutMs);
      const onLine = (line: string) => {
        if (!predicate(line)) return;
        cleanup();
        resolve(line);
      };
      const onError = (error: Error) => {
        cleanup();
        reject(error);
      };
      const onExit = (code: number | null) => {
        cleanup();
        reject(new Error(`Network process exited before ${description}; code=${code ?? "signal"}`));
      };
      this.#listeners.add(onLine);
      this.#errorListeners.add(onError);
      child?.once("exit", onExit);
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
