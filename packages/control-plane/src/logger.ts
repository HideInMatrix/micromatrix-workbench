import type { LogLevel, PluginLogger } from "@micromatrix/plugin-kit";

import type { LogEntry, LogStore } from "./types.js";

export class BufferedPluginLogger implements PluginLogger, LogStore {
  readonly #limit: number;
  #nextId = 1;
  #entries: LogEntry[] = [];

  constructor(limit = 2_000) {
    this.#limit = limit;
  }

  log(level: LogLevel, message: string, fields?: Readonly<Record<string, unknown>>): void {
    const suffix = fields ? ` ${JSON.stringify(fields)}` : "";
    const line = `[${level}] ${message}${suffix}`;
    this.#entries.push({ id: this.#nextId++, time: Date.now() / 1_000, message: line });
    if (this.#entries.length > this.#limit) this.#entries.splice(0, this.#entries.length - this.#limit);
    if (level === "error") console.error(line);
    else if (level === "warn") console.warn(line);
    else console.log(line);
  }

  entries(after: number): { cursor: number; entries: readonly LogEntry[] } {
    const entries = this.#entries.filter((entry) => entry.id > after);
    return { cursor: this.#nextId - 1, entries };
  }

  clear(): number {
    this.#entries = [];
    return this.#nextId - 1;
  }
}
