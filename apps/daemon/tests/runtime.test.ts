import { describe, expect, it } from 'vitest'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { loadConfig, saveConfig } from '../src/config.js'
import { applySecretUpdate, RuntimeSupervisor } from '../src/runtime.js'

describe('secret update semantics', () => {
  it('distinguishes unchanged, set, and clear', () => {
    expect(applySecretUpdate('saved', { action: 'unchanged' })).toBe('saved')
    expect(applySecretUpdate('saved', { action: 'set', value: 'replacement' })).toBe('replacement')
    expect(applySecretUpdate('saved', { action: 'clear' })).toBeUndefined()
  })

  it('clears OAuth and provider secrets through RuntimeSupervisor.configure', async () => {
    const directory = mkdtempSync(join(tmpdir(), 'micromatrix-secret-clear-'))
    const runtime = new RuntimeSupervisor(loadConfig({
      MICROMATRIX_CONFIG_FILE: join(directory, 'runtime.json'),
      MICROMATRIX_WORKSPACE: directory,
      MICROMATRIX_OAUTH_PASSWORD: 'saved-password',
      MICROMATRIX_TUNNEL_TOKEN: 'saved-token',
      MICROMATRIX_NETWORK_PROVIDER: 'cloudflare',
      MICROMATRIX_PUBLIC_URL: 'https://mcp.example.com',
      MICROMATRIX_PORT: '19534',
      MICROMATRIX_CONTROL_PORT: '19533',
    }), { log() {} })
    try {
      await runtime.configure({
        name: 'Pi MCP Runtime',
        workspace: directory,
        host: '127.0.0.1',
        port: 19534,
        permissionMode: 'safe',
        oauthPassword: { action: 'clear' },
        rememberSecrets: true,
        network: {
          provider: 'cloudflare',
          publicUrl: '',
          options: {},
          secretUpdates: { tunnel_token: { action: 'clear' } },
        },
      })
      expect(runtime.snapshot().oauthEnabled).toBe(false)
      expect(runtime.snapshot().networkOptions.tunnel_token).toBeUndefined()
      expect(readFileSync(join(directory, 'runtime.json'), 'utf8')).not.toContain('saved-')
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })
})

describe('RuntimeSupervisor exposure guard', () => {
  it('defers non-loopback authentication validation until explicit start', async () => {
    const directory = mkdtempSync(join(tmpdir(), 'micromatrix-runtime-guard-'))
    const runtime = new RuntimeSupervisor(loadConfig({
        MICROMATRIX_CONFIG_FILE: join(directory, 'runtime.json'),
        MICROMATRIX_WORKSPACE: directory,
        MICROMATRIX_HOST: '0.0.0.0',
        MICROMATRIX_PORT: '19434',
        MICROMATRIX_CONTROL_PORT: '19433',
        MICROMATRIX_NETWORK_PROVIDER: 'external',
        MICROMATRIX_PUBLIC_URL: 'http://127.0.0.1:19434',
        MICROMATRIX_REMEMBER_SECRETS: 'false',
      }), { log() {} })
    try {
      expect(runtime.snapshot()).toMatchObject({ running: false, exitReason: '', publicMcpUrl: '' })
      await expect(runtime.start()).rejects.toThrow('requires an OAuth password')
      expect(runtime.snapshot().exitReason).toContain('requires an OAuth password')
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it('fails tunnel executable preflight without publishing a fallback URL', async () => {
    const directory = mkdtempSync(join(tmpdir(), 'micromatrix-runtime-preflight-'))
    const runtime = new RuntimeSupervisor(loadConfig({
      MICROMATRIX_CONFIG_FILE: join(directory, 'runtime.json'),
      MICROMATRIX_WORKSPACE: directory,
      MICROMATRIX_HOST: '127.0.0.1',
      MICROMATRIX_PORT: '19634',
      MICROMATRIX_CONTROL_PORT: '19633',
      MICROMATRIX_NETWORK_PROVIDER: 'cloudflare',
      MICROMATRIX_TUNNEL_EXECUTABLE: join(directory, 'missing-cloudflared'),
      MICROMATRIX_OAUTH_PASSWORD: 'test-only-password',
    }), { log() {} })
    try {
      await expect(runtime.start()).rejects.toThrow('Tunnel executable not found or not executable')
      expect(runtime.snapshot()).toMatchObject({ running: false, publicMcpUrl: '' })
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })
})

describe('configuration transactions', () => {
  function fixture() {
    const directory = mkdtempSync(join(tmpdir(), 'micromatrix-config-transaction-'))
    const config = loadConfig({
      MICROMATRIX_CONFIG_FILE: join(directory, 'runtime.json'),
      MICROMATRIX_WORKSPACE: directory,
      MICROMATRIX_OAUTH_PASSWORD: 'original-password',
    })
    const runtime = new RuntimeSupervisor(config, { log() {} })
    const update = {
      name: 'replacement', workspace: directory, host: '127.0.0.1', port: 8234,
      permissionMode: 'dangerous' as const,
      oauthPassword: { action: 'clear' as const }, rememberSecrets: false,
      network: { provider: 'external' as const, publicUrl: '', options: {}, secretUpdates: {} },
    }
    return { directory, config, runtime, update }
  }

  it('preserves configuration, tools, policy and disk when provider validation fails', async () => {
    const { directory, config, runtime, update } = fixture()
    saveConfig(config, true)
    const before = runtime.snapshot()
    const disk = readFileSync(config.configFile, 'utf8')
    try {
      await expect(runtime.configure({
        ...update,
        network: { ...update.network, provider: 'frp' },
      })).rejects.toThrow('FRP requires a client config file')
      expect(runtime.snapshot()).toEqual(before)
      expect(runtime.snapshot().tools).toHaveLength(6)
      expect(runtime.approval.mode).toBe('safe')
      expect(readFileSync(config.configFile, 'utf8')).toBe(disk)
      await runtime.configure(update)
      expect(runtime.snapshot()).toMatchObject({ name: 'replacement', oauthEnabled: false })
      expect(runtime.snapshot().tools).toHaveLength(6)
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it('preserves state when persisting configuration or a plugin toggle fails', async () => {
    const { directory, config, runtime, update } = fixture()
    mkdirSync(config.configFile) // Atomic rename cannot replace a directory.
    const before = runtime.snapshot()
    try {
      await expect(runtime.configure(update)).rejects.toThrow()
      expect(runtime.snapshot()).toEqual(before)
      await expect(runtime.setPluginEnabled('shell', true)).rejects.toThrow()
      expect(runtime.snapshot()).toEqual(before)
      expect(runtime.approval.mode).toBe('safe')
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it('rejects control/MCP port collisions without mutating state', async () => {
    const { directory, config, runtime, update } = fixture()
    const before = runtime.snapshot()
    try {
      await expect(runtime.configure({ ...update, port: config.controlPort })).rejects.toThrow('must differ')
      expect(runtime.snapshot()).toEqual(before)
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it('loads incomplete provider configuration without creating or running it', async () => {
    const directory = mkdtempSync(join(tmpdir(), 'micromatrix-incomplete-config-'))
    const runtime = new RuntimeSupervisor(loadConfig({
      MICROMATRIX_CONFIG_FILE: join(directory, 'runtime.json'),
      MICROMATRIX_WORKSPACE: directory,
      MICROMATRIX_NETWORK_PROVIDER: 'frp',
      MICROMATRIX_OAUTH_PASSWORD: 'test-password',
    }), { log() {} })
    try {
      expect(runtime.snapshot()).toMatchObject({ running: false, networkProvider: 'frp', exitReason: '' })
      expect(runtime.snapshot().tools).toHaveLength(6)
      await expect(runtime.start()).rejects.toThrow('FRP requires a client config file')
      expect(runtime.snapshot().tools).toHaveLength(6)
    } finally {
      await runtime.dispose()
      rmSync(directory, { recursive: true, force: true })
    }
  })
})
