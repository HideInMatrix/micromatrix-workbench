import { createHash } from 'node:crypto'
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { DesktopCommandRouter } from '@micromatrix/control-plane'
import { describe, expect, it, vi } from 'vitest'

import { loadConfig } from '../src/config.js'
import { RuntimeSupervisor } from '../src/runtime.js'

interface OAuthTokens {
  readonly access_token: string
  readonly refresh_token: string
}

interface PermissionRequest {
  readonly request_id: string
  readonly client_id: string
  readonly client_name: string
  readonly authentication: string
}

async function availablePort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const port = typeof address === 'object' && address ? address.port : 0
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  if (!port) throw new Error('Failed to allocate an integration-test port')
  return port
}

async function oauthLogin(origin: string, resource: string, password: string): Promise<{
  readonly clientId: string
  readonly tokens: OAuthTokens
}> {
  const metadata = await fetch(`${origin}/.well-known/oauth-protected-resource/mcp`).then(response => response.json())
  expect(metadata).toMatchObject({ resource, authorization_servers: [origin] })

  const registrationResponse = await fetch(`${origin}/register`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      client_name: 'Daemon integration client',
      redirect_uris: ['http://127.0.0.1:4545/callback'],
    }),
  })
  expect(registrationResponse.status).toBe(201)
  const registration = await registrationResponse.json() as { client_id: string }

  const verifier = 'integration-verifier-with-at-least-forty-three-characters'
  const query = new URLSearchParams({
    response_type: 'code',
    client_id: registration.client_id,
    redirect_uri: 'http://127.0.0.1:4545/callback',
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
    scope: 'mcp',
    resource,
    state: 'integration-state',
  })
  const authorizationResponse = await fetch(`${origin}/authorize?${query}`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ password }),
    redirect: 'manual',
  })
  expect(authorizationResponse.status).toBe(302)
  const callback = new URL(authorizationResponse.headers.get('location') ?? '')
  expect(callback.searchParams.get('state')).toBe('integration-state')

  const tokenResponse = await fetch(`${origin}/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: registration.client_id,
      redirect_uri: 'http://127.0.0.1:4545/callback',
      code: callback.searchParams.get('code') ?? '',
      code_verifier: verifier,
    }),
  })
  expect(tokenResponse.status).toBe(200)
  return {
    clientId: registration.client_id,
    tokens: await tokenResponse.json() as OAuthTokens,
  }
}

async function refreshAccessToken(origin: string, clientId: string, refreshToken: string): Promise<OAuthTokens> {
  const response = await fetch(`${origin}/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: clientId,
      refresh_token: refreshToken,
    }),
  })
  expect(response.status).toBe(200)
  return response.json() as Promise<OAuthTokens>
}

async function mcpClient(mcpUrl: string, accessToken: string): Promise<Client> {
  const client = new Client({ name: 'daemon-integration-test', version: '1.0.0' })
  await client.connect(new StreamableHTTPClientTransport(new URL(mcpUrl), {
    requestInit: { headers: { authorization: `Bearer ${accessToken}` } },
  }))
  return client
}

describe('OAuth MCP runtime flow', () => {
  it('runs DCR + PKCE, approval, a Pi workspace tool, and refresh-session reuse', async () => {
    const workspace = mkdtempSync(join(tmpdir(), 'micromatrix-oauth-mcp-'))
    const port = await availablePort()
    const password = 'integration-only-password'
    const runtime = new RuntimeSupervisor(loadConfig({
      MICROMATRIX_CONFIG_FILE: join(workspace, 'runtime.json'),
      MICROMATRIX_WORKSPACE: workspace,
      MICROMATRIX_HOST: '127.0.0.1',
      MICROMATRIX_PORT: String(port),
      MICROMATRIX_CONTROL_PORT: String(port === 65_535 ? port - 1 : port + 1),
      MICROMATRIX_NETWORK_PROVIDER: 'external',
      MICROMATRIX_OAUTH_PASSWORD: password,
      MICROMATRIX_PERMISSION_MODE: 'safe',
    }), { log() {} })
    const control = new DesktopCommandRouter({
      appName: 'Integration Test',
      version: 'test',
      host: '127.0.0.1',
      port: port === 65_535 ? port - 1 : port + 1,
      runtime,
      approvals: runtime.approval,
      logs: { entries: () => ({ cursor: 0, entries: [] }), clear: () => 0 },
    })

    let client: Client | undefined
    let refreshedClient: Client | undefined
    try {
      expect(runtime.snapshot().publicMcpUrl).toBe('')
      const starting = runtime.start()
      const reconfiguring = runtime.configure({
        name: 'must-not-replace-starting-runtime', workspace, host: '127.0.0.1', port,
        permissionMode: 'safe', rememberSecrets: false, oauthPassword: { action: 'unchanged' },
        network: { provider: 'frp', publicUrl: '', options: {}, secretUpdates: {} },
      })
      await expect(reconfiguring).rejects.toThrow('Stop the runtime before changing its configuration')
      await starting
      expect(runtime.snapshot().networkProvider).toBe('external')
      expect(runtime.snapshot().tools).toHaveLength(6)
      const mcpUrl = runtime.snapshot().publicMcpUrl
      const origin = new URL(mcpUrl).origin

      const unauthorized = await fetch(mcpUrl, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
      })
      expect(unauthorized.status).toBe(401)
      expect(unauthorized.headers.get('www-authenticate')).toContain('oauth-protected-resource')

      const login = await oauthLogin(origin, mcpUrl, password)
      client = await mcpClient(mcpUrl, login.tokens.access_token)
      expect((await client.listTools()).tools.map(tool => tool.name)).toContain('write')

      const firstWrite = client.callTool({
        name: 'write',
        arguments: { path: 'approved.txt', content: 'approved through OAuth MCP' },
      })
      let requests: PermissionRequest[] = []
      await vi.waitFor(async () => {
        requests = await control.dispatch({ method: 'list_permission_requests', args: [] }) as PermissionRequest[]
        expect(requests).toHaveLength(1)
      })
      const approval = requests[0]
      expect(approval).toMatchObject({
        authentication: 'oauth',
        client_id: login.clientId,
        client_name: 'Daemon integration client',
      })
      expect(() => readFileSync(join(workspace, 'approved.txt'), 'utf8')).toThrow()
      await expect(control.dispatch({
        method: 'respond_permission_request',
        args: [approval?.request_id ?? '', 'session'],
      })).resolves.toBe(true)
      await expect(firstWrite).resolves.toMatchObject({
        content: [{ type: 'text', text: expect.stringContaining('approved.txt') }],
      })
      expect(readFileSync(join(workspace, 'approved.txt'), 'utf8')).toBe('approved through OAuth MCP')

      await client.close()
      client = undefined
      const refreshed = await refreshAccessToken(origin, login.clientId, login.tokens.refresh_token)
      refreshedClient = await mcpClient(mcpUrl, refreshed.access_token)
      await expect(refreshedClient.callTool({
        name: 'write',
        arguments: { path: 'refresh-session.txt', content: 'same approved session' },
      })).resolves.toMatchObject({
        content: [{ type: 'text', text: expect.stringContaining('refresh-session.txt') }],
      })
      await expect(control.dispatch({ method: 'list_permission_requests', args: [] })).resolves.toEqual([])
      expect(readFileSync(join(workspace, 'refresh-session.txt'), 'utf8')).toBe('same approved session')
      await refreshedClient.close()
      refreshedClient = undefined
      await runtime.stop()
      expect(runtime.snapshot().publicMcpUrl).toBe('')
      // Lifecycle commands are serialized; a stop/start cannot accidentally
      // return the other operation's promise or retain an old OAuth grant.
      await Promise.all([runtime.start(), runtime.stop(), runtime.start()])
      expect(runtime.snapshot().running).toBe(true)
      expect(await fetch(mcpUrl, {
        method: 'POST', headers: { authorization: `Bearer ${refreshed.access_token}`, 'content-type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }),
      }).then(response => response.status)).toBe(401)
      await runtime.stop()
    } finally {
      await client?.close().catch(() => undefined)
      await refreshedClient?.close().catch(() => undefined)
      await runtime.dispose()
      rmSync(workspace, { recursive: true, force: true })
    }
  })

  it.skipIf(process.platform === 'win32')('stops MCP and clears its URL when cloudflared exits unexpectedly', async () => {
    const workspace = mkdtempSync(join(tmpdir(), 'micromatrix-cloudflare-exit-'))
    const executable = join(workspace, 'fake-cloudflared')
    writeFileSync(executable, '#!/bin/sh\necho "https://fixture.trycloudflare.com"\nsleep 0.2\nexit 7\n')
    chmodSync(executable, 0o755)
    const port = await availablePort()
    const runtime = new RuntimeSupervisor(loadConfig({
      MICROMATRIX_CONFIG_FILE: join(workspace, 'runtime.json'),
      MICROMATRIX_WORKSPACE: workspace,
      MICROMATRIX_HOST: '127.0.0.1',
      MICROMATRIX_PORT: String(port),
      MICROMATRIX_CONTROL_PORT: String(port === 65_535 ? port - 1 : port + 1),
      MICROMATRIX_NETWORK_PROVIDER: 'cloudflare',
      MICROMATRIX_TUNNEL_EXECUTABLE: executable,
      MICROMATRIX_OAUTH_PASSWORD: 'test-only-password',
    }), { log() {} })
    try {
      await runtime.start()
      expect(runtime.snapshot()).toMatchObject({
        running: true,
        publicMcpUrl: 'https://fixture.trycloudflare.com/mcp',
      })
      await vi.waitFor(() => expect(runtime.snapshot().running).toBe(false))
      expect(runtime.snapshot().publicMcpUrl).toBe('')
      expect(runtime.snapshot().exitReason).toContain('cloudflared exited unexpectedly; code=7')
      await runtime.stop()
      await expect(fetch(`http://127.0.0.1:${port}/healthz`, {
        signal: AbortSignal.timeout(500),
      })).rejects.toThrow()
    } finally {
      await runtime.dispose()
      rmSync(workspace, { recursive: true, force: true })
    }
  })
})
