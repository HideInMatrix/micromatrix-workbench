import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { request } from 'node:http'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { expect, it } from 'vitest'

async function availablePort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const port = typeof address === 'object' && address ? address.port : 0
  await new Promise<void>(resolve => server.close(() => resolve()))
  return port
}

function chunkedOversize(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = request(url, { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' } }, res => {
      res.resume()
      res.once('end', () => resolve(res.statusCode ?? 0))
      res.once('error', reject)
    })
    req.once('error', reject)
    for (let index = 0; index < 7; index++) req.write('x'.repeat(10_000))
    req.end()
  })
}

it('boots incomplete legacy config idle, starts only on command, and survives oversized OAuth requests', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'micromatrix-manual-start-'))
  const configFile = join(directory, 'runtime.json')
  const port = await availablePort()
  let controlPort = await availablePort()
  while (controlPort === port) controlPort = await availablePort()
  // Even an older auto-start setting and an unfinished FRP configuration must
  // not crash startup or prevent the operator from reaching the configuration UI.
  writeFileSync(configFile, JSON.stringify({
    enabled: true,
    workspace: join(directory, 'not-selected-yet'),
    network: { provider: 'frp', options: {} },
  }))
  const child = spawn(process.execPath, ['--import', 'tsx', fileURLToPath(new URL('../src/main.ts', import.meta.url))], {
    env: {
      ...process.env,
      MICROMATRIX_CONFIG_FILE: configFile,
      MICROMATRIX_WORKSPACE: '', MICROMATRIX_HOST: '127.0.0.1',
      MICROMATRIX_PORT: String(port), MICROMATRIX_CONTROL_HOST: '127.0.0.1',
      MICROMATRIX_CONTROL_PORT: String(controlPort), MICROMATRIX_ENABLED: 'true',
      MICROMATRIX_NETWORK_PROVIDER: '', AGENT_RUNTIME_NETWORK_PROVIDER: '',
      MICROMATRIX_PUBLIC_URL: '', AGENT_RUNTIME_SERVER_URL: '',
      MICROMATRIX_OAUTH_PASSWORD: '', MICROMATRIX_AUTH_TOKEN: 'test-static-bearer',
      MICROMATRIX_REMEMBER_SECRETS: 'false', MICROMATRIX_ENABLE_SHELL: 'false',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  child.on('error', error => { output += String(error) })
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()))
  const control = `http://127.0.0.1:${controlPort}`
  const origin = `http://127.0.0.1:${port}`
  async function call(method: string, ...args: unknown[]) {
    const response = await fetch(`${control}/api/desktop`, {
      method: 'POST', headers: { origin: control, 'content-type': 'application/json' },
      body: JSON.stringify({ method, args }),
    })
    const data = await response.json()
    expect(response.status, JSON.stringify(data)).toBe(200)
    return data
  }
  let client: Client | undefined
  try {
    let ready = false
    for (let index = 0; index < 80; index++) {
      try { ready = (await fetch(`${control}/healthz`, { signal: AbortSignal.timeout(300) })).ok } catch { /* startup */ }
      if (ready || child.exitCode !== null || child.signalCode !== null) break
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    expect(ready, output).toBe(true)
    expect((await call('bootstrap')).runtime).toMatchObject({ running: false, exit_reason: '', network: { provider: 'frp' } })
    await expect(fetch(`${origin}/healthz`, { signal: AbortSignal.timeout(300) })).rejects.toThrow()

    await call('configure_runtime', {
      name: 'Manual runtime', workspace: directory, host: '127.0.0.1', port,
      permission_mode: 'safe', remember_secrets: false,
      oauth_password_update: { action: 'set', value: 'test-oauth-password' },
      network: { provider: 'external', public_url: '', options: {}, secret_updates: {} },
    })
    expect(await call('get_runtime')).toMatchObject({ running: false, public_mcp_url: '' })
    await expect(fetch(`${origin}/healthz`, { signal: AbortSignal.timeout(300) })).rejects.toThrow()
    expect(await call('start_runtime')).toMatchObject({ running: true })

    for (const endpoint of ['/token', '/authorize', '/revoke', '/register']) {
      const response = await fetch(`${origin}${endpoint}`, {
        method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: 'x'.repeat(70_000),
      })
      expect(response.status).toBe(413)
      expect(await response.json()).toMatchObject({ error: 'invalid_request' })
      expect(await chunkedOversize(`${origin}${endpoint}`)).toBe(413)
      expect(child.exitCode, output).toBeNull()
      expect(await fetch(`${origin}/healthz`).then(response => response.status)).toBe(200)
    }
    expect(await fetch(`${origin}/token`, { method: 'POST', body: 'grant_type=invalid' }).then(response => response.status)).toBe(400)
    client = new Client({ name: 'oversize-regression', version: 'test' })
    await client.connect(new StreamableHTTPClientTransport(new URL(`${origin}/mcp`), {
      requestInit: { headers: { authorization: 'Bearer test-static-bearer' } },
    }))
    expect((await client.listTools()).tools.map(tool => tool.name)).toContain('read')
    await client.close()
    client = undefined
    expect(await call('stop_runtime')).toMatchObject({ running: false, public_mcp_url: '' })
    expect(output).not.toContain('auto-start failed')
  } finally {
    await client?.close().catch(() => undefined)
    child.kill('SIGTERM')
    const timer = setTimeout(() => child.kill('SIGKILL'), 3_000)
    await exited
    clearTimeout(timer)
    rmSync(directory, { recursive: true, force: true })
  }
}, 15_000)
