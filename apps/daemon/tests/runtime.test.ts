import { describe, expect, it } from 'vitest'

import { loadConfig } from '../src/config.js'
import { RuntimeSupervisor } from '../src/runtime.js'

describe('RuntimeSupervisor exposure guard', () => {
  it('requires authentication when MCP listens on a non-loopback host', () => {
    expect(() => new RuntimeSupervisor(loadConfig({
        MICROMATRIX_CONFIG_FILE: '/tmp/micromatrix-runtime-guard-missing.json',
        MICROMATRIX_WORKSPACE: '/tmp',
        MICROMATRIX_HOST: '0.0.0.0',
        MICROMATRIX_PORT: '19434',
        MICROMATRIX_CONTROL_PORT: '19433',
        MICROMATRIX_NETWORK_PROVIDER: 'external',
        MICROMATRIX_PUBLIC_URL: 'http://127.0.0.1:19434',
        MICROMATRIX_REMEMBER_SECRETS: 'false',
      }), { log() {} }),
    ).toThrow('requires OAuth or a static Bearer token')
  })
})
