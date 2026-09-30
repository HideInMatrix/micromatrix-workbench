import type { LogLevel, PluginLogger } from "./types.js";

export class ConsolePluginLogger implements PluginLogger {
  log(level: LogLevel, message: string, fields?: Readonly<Record<string, unknown>>): void {
    const suffix = fields ? ` ${JSON.stringify(fields)}` : "";
    const line = `[${level}] ${message}${suffix}`;
    if (level === "error") console.error(line);
    else if (level === "warn") console.warn(line);
    else console.log(line);
  }
}
