import { describe, expect, it } from 'vitest'
import { PluginRegistry } from '@micromatrix/plugin-kit'
import type { McpAuthorization } from '@micromatrix/oauth'
import { McpHttpService } from '../src/http-service.js'

describe('HTTP request exception boundary', () => {
  it('contains authorization handler failures without taking down the listener', async () => {
    const registry = new PluginRegistry({ workspace: '/tmp', logger: { log() {} } })
    const authorization: McpAuthorization = {
      oauthEnabled: true, protectsRequests: true,
      async handle(_request, _response, url) {
        if (url.pathname === '/broken') throw new Error('private internal details')
        return false
      },
      async authorize() { return undefined },
      challenge() { return 'Bearer' },
    }
    const server = new McpHttpService({ host: '127.0.0.1', port: 0, registry, authorization, logger: { log() {} } })
    await server.start()
    try {
      const response = await fetch(`${server.localBaseUrl}/broken`)
      expect(response.status).toBe(500)
      expect(await response.json()).toEqual({ error: 'internal_error' })
      expect(await fetch(`${server.localBaseUrl}/healthz`).then(response => response.status)).toBe(200)
    } finally {
      await server.stop()
      await registry.dispose()
    }
  })
})
