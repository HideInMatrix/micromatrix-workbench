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
  setPublicOrigin?(origin: string): void;
  challenge(request: IncomingMessage, resourcePath: string): string;
}

export interface LocalOAuthOptions {
  readonly publicOrigin?: string;
  readonly limits?: { readonly requestsPerMinute?: number; readonly loginAttemptsPerMinute?: number; readonly maxStateEntries?: number };
  readonly password: string | undefined;
  readonly staticBearerToken: string | undefined;
  readonly accessTokenTtlSeconds?: number;
  readonly refreshTokenTtlSeconds?: number;
}
