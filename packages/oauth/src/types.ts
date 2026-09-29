import type { IncomingMessage, ServerResponse } from "node:http";

export interface McpAuthorization {
  readonly oauthEnabled: boolean;
  readonly protectsRequests: boolean;
  handle(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean>;
  authorize(request: IncomingMessage): Promise<boolean>;
  challenge(request: IncomingMessage, resourcePath: string): string;
}

export interface LocalOAuthOptions {
  readonly password: string | undefined;
  readonly staticBearerToken: string | undefined;
  readonly accessTokenTtlSeconds?: number;
  readonly refreshTokenTtlSeconds?: number;
}
