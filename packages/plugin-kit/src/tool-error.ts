export class ExternalMcpError extends Error {
  constructor(readonly result: Readonly<Record<string, unknown>>) {
    super("External MCP tool returned an error");
    this.name = "ExternalMcpError";
  }
}
