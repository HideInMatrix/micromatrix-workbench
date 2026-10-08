import { execFile, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";

import type { PluginLogger } from "@micromatrix/plugin-kit";

export class ManagedProcess {
  readonly #logger: PluginLogger;
  #child: ChildProcessWithoutNullStreams | undefined;
  #recent: string[] = [];
  #listeners = new Set<(line: string) => void>();
  #error: Error | undefined;
  #errorListeners = new Set<(error: Error) => void>();
  #unexpectedExit: ((error: Error) => void) | undefined;
  #stopping = false;
  #failureReported = false;

  constructor(logger: PluginLogger) {
    this.#logger = logger;
  }

  get running(): boolean {
    return Boolean(this.#child && this.#child.exitCode === null && this.#child.signalCode === null);
  }
  /** Bounded diagnostic evidence for the owning Provider; no live callbacks. */
  recentOutput(): readonly string[] { return [...this.#recent]; }

  start(executable: string, args: readonly string[], label: string): void {
    if (this.running) throw new Error(`${label} is already running`);
    this.#recent = [];
    this.#error = undefined;
    this.#unexpectedExit = undefined;
    this.#stopping = false;
    this.#failureReported = false;
    this.#child = spawn(executable, [...args], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      detached: process.platform !== "win32",
    });
    this.#child.once("error", (error) => {
      const failure = new Error(`${label} spawn error: ${error.message}`, { cause: error });
      this.#error = failure;
      this.#logger.log("error", failure.message);
      for (const listener of this.#errorListeners) listener(failure);
      this.#reportUnexpected(failure);
    });
    this.#child.once("exit", (code, signal) => {
      if (this.#stopping) return;
      const failure = new Error(`${label} exited unexpectedly; code=${code ?? "null"}; signal=${signal ?? "none"}`);
      this.#error = failure;
      this.#logger.log("error", failure.message);
      this.#reportUnexpected(failure);
    });
    this.#read(this.#child.stdout, label);
    this.#read(this.#child.stderr, label);
  }

  monitorUnexpectedExit(listener: (error: Error) => void): void {
    this.#unexpectedExit = listener;
    if (this.#error && !this.running && !this.#stopping) this.#reportUnexpected(this.#error);
  }

  waitFor(predicate: (line: string) => boolean, timeoutMs: number, description: string, signal?: AbortSignal): Promise<string> {
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (this.#error) return Promise.reject(this.#error);
    const recent = this.#recent.find(predicate); if (recent) return Promise.resolve(recent);
    return new Promise((resolve, reject) => {
      const child = this.#child;
      const cleanup = () => {
        clearTimeout(timeout);
        this.#listeners.delete(onLine);
        this.#errorListeners.delete(onError);
        child?.off("exit", onExit);
        signal?.removeEventListener("abort", onAbort);
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
      const onAbort = () => { cleanup(); reject(signal!.reason); };
      this.#listeners.add(onLine);
      this.#errorListeners.add(onError);
      child?.once("exit", onExit);
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted) onAbort();
    });
  }

  async stop(): Promise<void> {
    const child = this.#child;
    this.#child = undefined;
    this.#stopping = true;
    this.#unexpectedExit = undefined;
    if (!child) return;
    if (child.exitCode !== null || child.signalCode !== null) {
      if (process.platform !== "win32") await this.#terminate(child, true); // Owned descendants may outlive the leader.
      return;
    }
    const exited = new Promise<void>(resolve => {
      const done = () => { clearTimeout(timer); child.off("exit", done); resolve(); };
      const timer = setTimeout(done, 3000); child.once("exit", done);
    });
    await this.#terminate(child, false);
    await exited;
    if (process.platform !== "win32" || child.exitCode === null && child.signalCode === null) {
      await this.#terminate(child, true);
      if (child.exitCode !== null || child.signalCode !== null) return;
      await new Promise<void>(resolve => {
        const done = () => { clearTimeout(timer); child.off("exit", done); resolve(); };
        const timer = setTimeout(done, 1000); child.once("exit", done);
      });
    }
  }
  async #terminate(child: ChildProcessWithoutNullStreams, force: boolean): Promise<void> {
    if (!child.pid || process.platform === "win32" && (child.exitCode !== null || child.signalCode !== null)) return;
    if (process.platform === "win32") await new Promise<void>(resolve => execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, timeout: 3000 }, () => resolve()));
    else try { process.kill(-child.pid, force ? "SIGKILL" : "SIGTERM"); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
  }

  #reportUnexpected(error: Error): void {
    if (this.#stopping || this.#failureReported || !this.#unexpectedExit) return;
    this.#failureReported = true;
    this.#unexpectedExit(error);
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
    this.#recent.push(line); if (this.#recent.length > 64) this.#recent.shift();
    for (const listener of this.#listeners) listener(line);
  }
}

async function executableCandidate(candidate: string): Promise<boolean> {
  try {
    const value = await stat(candidate);
    if (!value.isFile()) return false;
    await access(candidate, process.platform === "win32" ? constants.F_OK : constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export async function assertExecutable(executable: string): Promise<void> {
  const value = executable.trim();
  if (!value) throw new Error("Tunnel executable is not configured");
  const direct = path.isAbsolute(value) || value.includes("/") || value.includes("\\");
  const extensions = process.platform === "win32" && !path.extname(value)
    ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM").split(";")
    : [""];
  const bases = direct
    ? [path.resolve(value)]
    : (process.env.PATH ?? "").split(path.delimiter).filter(Boolean).map(directory => path.join(directory, value));
  for (const base of bases) {
    for (const extension of extensions) {
      if (await executableCandidate(`${base}${extension.toLowerCase()}`)) return;
      if (extension && await executableCandidate(`${base}${extension.toUpperCase()}`)) return;
    }
  }
  throw new Error(`Tunnel executable not found or not executable: ${executable}`);
}

export async function assertRegularFile(file: string, label: string): Promise<void> {
  try {
    if ((await stat(file)).isFile()) {
      await access(file, constants.R_OK);
      return;
    }
  } catch {
    // Fall through to the provider-specific error below.
  }
  throw new Error(`${label} is not a readable file: ${file}`);
}
