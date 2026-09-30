import { createHash } from 'node:crypto'
import { Readable } from 'node:stream'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it } from 'vitest'

import { LocalOAuthServer } from '../src/index.js'

interface CapturedResponse {
  status: number
  headers: Record<string, string>
  body: string
}

function request(url: string, method = 'GET', body = '', headers: Record<string, string> = {}): IncomingMessage {
  const stream = Readable.from(body ? [body] : []) as IncomingMessage
  stream.method = method
  stream.url = url
  stream.headers = { host: '127.0.0.1:8234', ...headers }
  return stream
}

function response(): { raw: ServerResponse; captured: CapturedResponse } {
  const captured: CapturedResponse = { status: 200, headers: {}, body: '' }
  const raw = {
    writableEnded: false,
    writeHead(status: number, headers: Record<string, string> = {}) {
      captured.status = status
      captured.headers = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), String(value)]))
      return this
    },
    end(value?: string) {
      captured.body = value ?? ''
      this.writableEnded = true
      return this
    },
  } as unknown as ServerResponse
  return { raw, captured }
}

async function invoke(oauth: LocalOAuthServer, url: string, method = 'GET', body = '') {
  const result = response()
  const handled = await oauth.handle(request(url, method, body), result.raw, new URL(url, 'http://127.0.0.1:8234'))
  expect(handled).toBe(true)
  return result.captured
}

describe('LocalOAuthServer', () => {
  it('identifies anonymous and static bearer sessions without exposing the token', async () => {
    const open = new LocalOAuthServer({ password: undefined, staticBearerToken: undefined })
    await expect(open.authorize(request('/mcp', 'POST'), '/mcp')).resolves.toMatchObject({
      authentication: 'anonymous',
      sessionId: 'local-anonymous',
    })

    const protectedServer = new LocalOAuthServer({ password: undefined, staticBearerToken: 'static-secret' })
    await expect(protectedServer.authorize(request('/mcp', 'POST'), '/mcp')).resolves.toBeUndefined()
    const principal = await protectedServer.authorize(request('/mcp', 'POST', '', {
      authorization: 'Bearer static-secret',
    }), '/mcp')
    expect(principal).toMatchObject({ authentication: 'static_bearer' })
    expect(principal?.sessionId).not.toContain('static-secret')
  })

  it('supports metadata, DCR and authorization-code PKCE', async () => {
    const oauth = new LocalOAuthServer({ password: 'correct horse battery staple' })
    const metadata = await invoke(oauth, '/.well-known/oauth-protected-resource/mcp')
    expect(JSON.parse(metadata.body)).toMatchObject({
      resource: 'http://127.0.0.1:8234/mcp',
      authorization_servers: ['http://127.0.0.1:8234'],
    })

    const registration = await invoke(oauth, '/register', 'POST', JSON.stringify({
      client_name: 'Web MCP Client',
      redirect_uris: ['http://127.0.0.1:4545/callback'],
    }))
    expect(registration.status).toBe(201)
    const client = JSON.parse(registration.body) as { client_id: string }

    const verifier = 'local-verifier-with-enough-entropy-for-this-test'
    const challenge = createHash('sha256').update(verifier).digest('base64url')
    const query = new URLSearchParams({
      response_type: 'code',
      client_id: client.client_id,
      redirect_uri: 'http://127.0.0.1:4545/callback',
      code_challenge: challenge,
      code_challenge_method: 'S256',
      scope: 'mcp',
      resource: 'http://127.0.0.1:8234/mcp',
      state: 'test-state',
    })
    expect((await invoke(oauth, `/authorize?${query}`)).status).toBe(200)

    const consent = await invoke(
      oauth,
      `/authorize?${query}`,
      'POST',
      new URLSearchParams({ password: 'correct horse battery staple' }).toString(),
    )
    expect(consent.status).toBe(302)
    const callback = new URL(consent.headers.location)
    expect(callback.searchParams.get('state')).toBe('test-state')

    const token = await invoke(oauth, '/token', 'POST', new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: client.client_id,
      redirect_uri: 'http://127.0.0.1:4545/callback',
      code: callback.searchParams.get('code') ?? '',
      code_verifier: verifier,
    }).toString())
    expect(token.status).toBe(200)
    const issued = JSON.parse(token.body) as { access_token: string; refresh_token: string; token_type: string; scope: string }
    expect(issued).toMatchObject({ token_type: 'Bearer', scope: 'mcp' })

    const principal = await oauth.authorize(request('/mcp', 'POST', '', {
      authorization: `Bearer ${issued.access_token}`,
    }), '/mcp')
    expect(principal).toMatchObject({
      authentication: 'oauth',
      clientId: client.client_id,
      clientName: 'Web MCP Client',
      scopes: ['mcp'],
      resource: 'http://127.0.0.1:8234/mcp',
    })
    await expect(oauth.authorize(request('/mcp', 'POST', '', {
      host: 'different.example:8234',
      authorization: `Bearer ${issued.access_token}`,
    }), '/mcp')).resolves.toBeUndefined()

    const refreshed = await invoke(oauth, '/token', 'POST', new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: client.client_id,
      refresh_token: issued.refresh_token,
    }).toString())
    const refreshedToken = JSON.parse(refreshed.body) as { access_token: string }
    const refreshedPrincipal = await oauth.authorize(request('/mcp', 'POST', '', {
      authorization: `Bearer ${refreshedToken.access_token}`,
    }), '/mcp')
    expect(refreshedPrincipal?.sessionId).toBe(principal?.sessionId)
  })

  it('rejects non-HTTPS non-loopback redirect URIs', async () => {
    const oauth = new LocalOAuthServer({ password: 'secret' })
    const result = await invoke(oauth, '/register', 'POST', JSON.stringify({
      redirect_uris: ['http://example.com/callback'],
    }))
    expect(result.status).toBe(400)
    expect(JSON.parse(result.body)).toMatchObject({ error: 'invalid_redirect_uri' })
  })
})
