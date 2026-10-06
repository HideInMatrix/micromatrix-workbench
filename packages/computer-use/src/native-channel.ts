import { MacApplicationChannel } from "./mac-application-channel.js";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { StringDecoder } from "node:string_decoder";
import { fail, ComputerUseError } from "./protocol.js";

/** Lazy, bounded fixed-helper IPC. Never execute model-provided commands. */
class StdioDesktopChannel {
  #child: ChildProcessWithoutNullStreams | undefined;
  #buffer = "";
  #pending: { id: number; resolve: (value: unknown) => void; reject: (error: Error) => void } | undefined;
  #id = 0; #closed = false;
  constructor(readonly helper: string) {}
  #start() {
    if (this.#closed) fail("CLOSED", "Computer Use service stopped");
    if (!existsSync(this.helper)) fail("HELPER_MISSING", "Build the native helper with npm run prepare:computer-use before starting this MCP");
    if (this.#child) return this.#child;
    const child = spawn(this.helper, [], { stdio: "pipe", shell: false, windowsHide: true });
    const decoder = new StringDecoder("utf8");
    this.#child = child;
    child.stderr.on("data", () => {});
    const disconnected = () => {
      if (this.#child !== child) return;
      this.#child = undefined; this.#buffer = "";
      this.#pending?.reject(new ComputerUseError("NATIVE_DISCONNECTED", "Native helper stopped; action outcome may be unknown. Observe again before retrying")); this.#pending = undefined;
    };
    child.on("error", disconnected); child.on("exit", disconnected);
    child.stdin.on("error", disconnected);
    child.stdout.on("data", (bytes: Buffer) => {
      this.#buffer += decoder.write(bytes);
      if (Buffer.byteLength(this.#buffer) > 1024 * 1024) { child.kill("SIGKILL"); disconnected(); return; }
      let newline;
      while ((newline = this.#buffer.indexOf("\n")) >= 0) {
        const line = this.#buffer.slice(0,newline); this.#buffer = this.#buffer.slice(newline+1);
        try {
          const reply = JSON.parse(line) as { id: number; result?: unknown; error?: { code: string; message: string } };
          if (this.#pending?.id !== reply.id) continue;
          if (reply.error) this.#pending.reject(new ComputerUseError(reply.error.code,reply.error.message)); else this.#pending.resolve(reply.result);
          this.#pending = undefined;
        } catch { child.kill("SIGKILL"); disconnected(); }
      }
    });
    return child;
  }
  async request(operation: string, params: Record<string,unknown> = {}, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted();
    if (this.#pending) fail("BUSY", "Native operation already in progress");
    const child = this.#start(), id = ++this.#id;
    const stop = () => { child.kill("SIGKILL"); };
    const timer = setTimeout(stop,10_000);
    signal?.addEventListener("abort",stop,{once:true});
    try {
      return await new Promise((resolve,reject) => {
        this.#pending = { id, resolve, reject };
        child.stdin.write(JSON.stringify({id,operation,...params})+"\n", error => { if(error) stop(); });
      });
    } finally { clearTimeout(timer); signal?.removeEventListener("abort",stop); }
  }
  async close() {
    this.#closed = true;
    const child = this.#child;
    if (!child) return;
    child.stdin.end();
    await new Promise<void>(resolve => {
      const timer = setTimeout(() => { child.kill("SIGKILL"); resolve(); },500);
      child.once("exit",()=>{clearTimeout(timer);resolve();});
    });
  }
}

/** macOS must launch a real app via LaunchServices, not a bare child inheriting the parent TCC identity. */
export class NativeDesktopChannel {
  readonly #backend: StdioDesktopChannel | MacApplicationChannel;
  constructor(readonly helper: string) {
    this.#backend = process.platform === "darwin" && helper.endsWith(".app")
      ? new MacApplicationChannel(helper) : new StdioDesktopChannel(helper);
  }
  request(operation: string, params: Record<string, unknown> = {}, signal?: AbortSignal) { return this.#backend.request(operation, params, signal); }
  close() { return this.#backend.close(); }
}
