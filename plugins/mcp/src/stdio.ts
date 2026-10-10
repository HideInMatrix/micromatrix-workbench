import spawn from "cross-spawn";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { ReadBuffer, serializeMessage } from "@modelcontextprotocol/sdk/shared/stdio.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";

/** SDK framing, but owns a process group rather than only the npx/uvx parent. */
export class OwnedStdioTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: JSONRPCMessage) => void;
  #process: ChildProcessWithoutNullStreams | undefined;
  #buffer = new ReadBuffer({ maxBufferSize: 4 * 1024 * 1024 });
  #closing: Promise<void> | undefined;
  #started = false;
  constructor(readonly command: string, readonly args: readonly string[], readonly env: Record<string, string>, readonly cwd: string) {}
  async start(): Promise<void> {
    if (this.#started) throw new Error("MCP transport already started");
    this.#started = true;
    const child = spawn(this.command, [...this.args], { cwd: this.cwd, env: this.env,
      stdio: "pipe", shell: false, windowsHide: true, detached: process.platform !== "win32" });
    this.#process = child;
    child.stderr.on("data", () => {}); // Never log upstream secrets.
    child.stdin.on("error", error => this.onerror?.(error));
    child.stdout.on("error", error => this.onerror?.(error));
    child.stdout.on("data", (chunk: Buffer) => {
      try { this.#buffer.append(chunk); let message; while ((message = this.#buffer.readMessage()) !== null) this.onmessage?.(message); }
      catch (error) { this.onerror?.(error as Error); void this.close(); }
    });
    child.once("exit", () => { void this.close(); }); // Clean descendants even when their parent exits first.
    child.once("close", () => this.onclose?.());
    await new Promise<void>((resolve, reject) => { child.once("spawn", resolve); child.once("error", reject); });
  }
  async send(message: JSONRPCMessage): Promise<void> {
    const child = this.#process;
    if (!child || this.#closing || child.exitCode !== null) throw new Error("MCP process disconnected");
    await new Promise<void>((resolve, reject) => child.stdin.write(serializeMessage(message), error => error ? reject(error) : resolve()));
  }
  close(): Promise<void> { return this.#closing ??= this.#close(); }
  async #close(): Promise<void> {
    const child = this.#process;
    if (!child) return;
    const pid = child.pid;
    if (pid && process.platform === "win32") {
      // taskkill /T operates only on this owned PID's tree, never image names.
      // Do not let the parent exit voluntarily before collecting its descendants.
      await new Promise<void>(resolve => {
        const killer = spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", shell: false });
        const timer = setTimeout(() => { killer.kill(); child.kill(); resolve(); }, 2000);
        killer.once("error", () => { clearTimeout(timer); child.kill(); resolve(); });
        killer.once("exit", () => { clearTimeout(timer); resolve(); });
      });
    } else if (pid) {
      // This group belongs exclusively to Runtime. Do not wait for stdin drain
      // or an upstream tool call before terminating it.
      try { process.kill(-pid, "SIGKILL"); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
    }
    if (child.pid && child.exitCode === null && child.signalCode === null) {
      await new Promise<void>(resolve => {
        const done = () => { clearTimeout(timer); child.off("exit", done); resolve(); };
        const timer = setTimeout(done, 1000);
        child.once("exit", done);
      });
    }
    child.stdin.destroy(); child.stdout.destroy(); child.stderr.destroy();
    this.#process = undefined;
    this.#buffer.clear();
  }
}
