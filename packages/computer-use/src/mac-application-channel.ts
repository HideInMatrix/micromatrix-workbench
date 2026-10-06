import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer, type Server, type Socket } from "node:net";
import { join } from "node:path";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { StringDecoder } from "node:string_decoder";
import { ComputerUseError, fail } from "./protocol.js";

const identity = "org.micromatrix.computer-use";
const disconnected = () => new ComputerUseError("NATIVE_DISCONNECTED", "Computer Use application stopped; action outcome may be unknown. Observe again before retrying");

/** Private, per-channel Unix socket. No public listener, reusable token, shell or inherited stdio/TCC identity. */
export class MacApplicationChannel {
  #server: Server | undefined;
  #socket: Socket | undefined;
  #launcher: ChildProcess | undefined;
  #directory = "";
  #pid = 0;
  #closed = false;
  #starting: Promise<Socket> | undefined;
  #disposing: Promise<void> | undefined;
  #cancelLaunch: ((error: Error) => void) | undefined;
  #id = 0;
  #pending: { id: number; resolve: (result: unknown) => void; reject: (error: Error) => void } | undefined;
  constructor(readonly application: string) {}

  async #start(): Promise<Socket> {
    if (this.#closed) fail("CLOSED", "Computer Use service stopped");
    if (this.#socket) return this.#socket;
    if (this.#starting) return this.#starting;
    this.#starting = (async () => { if (this.#directory || this.#disposing) await this.#dispose(); return await this.#launch(); })();
    try { return await this.#starting; }
    catch (error) { await this.#dispose(); throw error; }
    finally { this.#starting = undefined; this.#cancelLaunch = undefined; }
  }
  async #launch(): Promise<Socket> {
    if (!existsSync(join(this.application, "Contents/MacOS/micromatrix-computer"))) fail("HELPER_MISSING", "Install a complete Computer Use application bundle");
    // Darwin sockaddr_un has a short path limit; use /tmp rather than a long TMPDIR.
    this.#directory = await mkdtemp("/tmp/mm-cu-");
    await chmod(this.#directory, 0o700);
    const token = randomBytes(32).toString("hex");
    const socketPath = join(this.#directory, "ipc.sock");
    const channelFile = join(this.#directory, "channel.json");
    await writeFile(channelFile, JSON.stringify({ socket: socketPath, token }), { mode: 0o600, flag: "wx" });
    if (this.#closed) fail("CLOSED", "Computer Use service stopped");
    return await new Promise<Socket>((resolve, reject) => {
      let ready = false;
      const timer = setTimeout(() => reject(new ComputerUseError("NATIVE_LAUNCH_TIMEOUT", "Computer Use application did not connect via LaunchServices")), 12_000);
      const abort = (error: Error) => { clearTimeout(timer); if (!ready) reject(error); else this.#lost(); };
      this.#cancelLaunch = abort;
      this.#server = createServer(socket => {
        if (ready) { socket.destroy(); return; }
        let buffer = "", authenticated = false;
        const decoder = new StringDecoder("utf8");
        socket.setTimeout(3000, () => { if (!authenticated) socket.destroy(); });
        socket.on("error", () => { if (authenticated && this.#socket === socket) this.#lost(); });
        socket.on("close", () => { if (authenticated && this.#socket === socket) this.#lost(); });
        socket.on("data", bytes => {
          buffer += decoder.write(bytes);
          if (Buffer.byteLength(buffer) > 1024 * 1024) { socket.destroy(); return; }
          let newline;
          while ((newline = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
            try {
              const reply = JSON.parse(line);
              if (!authenticated) {
                const supplied = Buffer.from(typeof reply.token === "string" ? reply.token : "");
                const expected = Buffer.from(token);
                if (this.#closed || ready || supplied.length !== expected.length || !timingSafeEqual(supplied, expected)
                  || reply.bundle_id !== identity || !Number.isSafeInteger(reply.pid) || reply.pid <= 1) { socket.destroy(); return; }
                authenticated = ready = true; socket.setTimeout(0); clearTimeout(timer);
                this.#socket = socket; this.#pid = reply.pid;
                resolve(socket);
              } else {
                const pending = this.#pending;
                if (pending && pending.id === reply.id) {
                  if (reply.error) pending.reject(new ComputerUseError(reply.error.code, reply.error.message));
                  else pending.resolve(reply.result);
                  this.#pending = undefined;
                }
              }
            } catch { socket.destroy(); return; }
          }
        });
      });
      this.#server.on("error", error => abort(error));
      this.#server.listen(socketPath, () => {
        if (this.#closed) { abort(new ComputerUseError("CLOSED", "Computer Use service stopped")); return; }
        // LaunchServices gives this .app its own responsible process identity.
        const launcher = spawn("/usr/bin/open", ["-n", "-g", "-W", "-a", this.application, "--args", "--channel", channelFile], { stdio: "ignore", shell: false });
        this.#launcher = launcher;
        launcher.once("error", error => { if (this.#launcher === launcher) abort(error); });
        launcher.once("exit", () => { if (this.#launcher === launcher) abort(disconnected()); });
      });
    });
  }
  #lost() {
    this.#pending?.reject(disconnected()); this.#pending = undefined;
    this.#socket?.destroy(); this.#socket = undefined;
  }
  async request(operation: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted();
    if (this.#pending || this.#starting) fail("BUSY", "Native operation already in progress");
    const socket = await this.#start();
    if (this.#closed) fail("CLOSED", "Computer Use service stopped");
    signal?.throwIfAborted();
    const id = ++this.#id;
    const stop = () => { this.#pending?.reject(signal?.aborted ? signal.reason : new ComputerUseError("NATIVE_TIMEOUT", "Native operation timed out; observe before retrying")); this.#pending = undefined; void this.#dispose(); };
    const timer = setTimeout(stop, 10_000);
    signal?.addEventListener("abort", stop, { once: true });
    try {
      return await new Promise((resolve, reject) => {
        this.#pending = { id, resolve, reject };
        socket.write(JSON.stringify({ id, operation, ...params }) + "\n", error => { if (error) stop(); });
      });
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", stop); }
  }
  #dispose(): Promise<void> {
    return this.#disposing ??= this.#disposeOwned().finally(() => { this.#disposing = undefined; });
  }
  async #disposeOwned() {
    this.#lost();
    const launcher = this.#launcher, pid = this.#pid, server = this.#server, directory = this.#directory;
    this.#launcher = undefined; this.#pid = 0; this.#server = undefined; this.#directory = "";
    if (launcher && launcher.exitCode === null) await new Promise<void>(resolve => {
      const timer = setTimeout(() => {
        // Only the authenticated owned app instance, never a queried target application.
        if (launcher.exitCode === null && pid > 1) try { process.kill(pid, "SIGKILL"); } catch { /* Already gone. */ }
        launcher.kill(); resolve();
      }, 500);
      launcher.once("exit", () => { clearTimeout(timer); resolve(); });
    });
    server?.close();
    if (directory) await rm(directory, { recursive: true, force: true });
  }
  async close() {
    this.#closed = true;
    this.#cancelLaunch?.(new ComputerUseError("CLOSED", "Computer Use service stopped"));
    await this.#starting?.catch(() => {});
    await this.#dispose();
  }
}
