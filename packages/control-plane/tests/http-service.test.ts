import { describe, expect, it, vi } from 'vitest'
import { ControlPlaneHttpService } from '../src/http-service.js'
import type { ControlPlaneOptions } from '../src/types.js'

describe('embedded UI Origin handling', () => {
  it('accepts its own origin/loopback alias, while rejecting other sites and ports', async () => {
    const options: ControlPlaneOptions = {
      appName: 'test', version: 'test', host: '127.0.0.1', port: 0,
      runtime: {
        snapshot: () => ({
          runtimeId: 'default', name: 'test', workspace: '/tmp', host: '127.0.0.1', port: 8234,
          running: false, publicMcpUrl: '', urlMode: 'Local', exitReason: '',
          networkProvider: 'external', configuredPublicUrl: '', enableShell: false,
          oauthEnabled: false, rememberSecrets: false, permissionMode: 'safe',
          networkOptions: {}, pluginIds: ['workspace'], tools: [],
        }),
        start: vi.fn(), stop: vi.fn(), configure: vi.fn(), setPluginEnabled: vi.fn(),
      },
      logs: { entries: () => ({ cursor: 0, entries: [] }), clear: () => 0 },
      webAssets: { '/index.html': { contentType: 'text/html', bodyBase64: Buffer.from('<html>UI</html>').toString('base64') } },
    }
    const server = new ControlPlaneHttpService(options)
    await server.start()
    const origin = server.localBaseUrl
    const port = new URL(origin).port
    async function call(originHeader: string) {
      return fetch(`${origin}/api/desktop`, {
        method: 'POST', headers: { origin: originHeader, 'content-type': 'application/json' },
        body: JSON.stringify({ method: 'get_app_version', args: [] }),
      })
    }
    try {
      expect(await fetch(origin).then(response => response.text())).toBe('<html>UI</html>')
      for (const allowed of [origin, `http://localhost:${port}`, 'http://127.0.0.1:5173', 'tauri://localhost']) {
        const response = await call(allowed)
        expect(response.status).toBe(200)
        expect(response.headers.get('access-control-allow-origin')).toBe(allowed)
        expect(await response.json()).toBe('test')
      }
      for (const rejected of ['https://evil.example', `http://localhost.evil.example:${port}`, 'http://127.0.0.1:1']) {
        const response = await call(rejected)
        expect(response.status).toBe(403)
        expect(await response.json()).toMatchObject({ error: 'origin_not_allowed' })
      }
      const preflight = await fetch(`${origin}/api/desktop`, {
        method: 'OPTIONS', headers: { origin, 'access-control-request-method': 'POST' },
      })
      expect(preflight.status).toBe(204)
    } finally {
      await server.stop()
    }
  })
})
