import type { IncomingMessage, ServerResponse } from "node:http";

export interface McpPrincipal {
  readonly authentication: "anonymous" | "static_bearer" | "oauth";
  readonly subjectId: string;
  readonly sessionId: string;
  readonly clientId?: string;
  readonly clientName?: string;
  readonly scopes: readonly string[];
  readonly resource?: string;
}

export interface McpAuthorization {
  readonly oauthEnabled: boolean;
  readonly protectsRequests: boolean;
  handle(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean>;
  authorize(request: IncomingMessage, resourcePath: string): Promise<McpPrincipal | undefined>;
  challenge(request: IncomingMessage, resourcePath: string): string;
}

export interface LocalOAuthOptions {
  readonly password: string | undefined;
  readonly staticBearerToken: string | undefined;
  readonly accessTokenTtlSeconds?: number;
  readonly refreshTokenTtlSeconds?: number;
  /** Durable public DCR metadata only; authorization codes and tokens stay in memory. */
  readonly clientStorePath?: string;
}
