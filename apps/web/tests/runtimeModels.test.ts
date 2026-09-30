import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizedRuntimeDraft, runtimeUrl } from '../src/components/services/runtimeModels.ts'
import type { RuntimeDraft, RuntimeDto } from '../src/types.ts'

const draft: RuntimeDraft = {
  name: '  Pi Runtime  ',
  workspace: '  /workspace  ',
  oauth_password: '',
  oauth_password_configured: true,
  oauth_password_action: 'unchanged',
  host: '127.0.0.1',
  port: 8234,
  remember_secrets: false,
  permission_mode: 'safe',
  network: {
    provider: 'external',
    public_url: 'https://mcp.example.com///',
    options: {},
    configured_secrets: [],
    secret_actions: {},
  },
}

test('normalizes the singleton runtime configuration', () => {
  const normalized = normalizedRuntimeDraft(draft)
  assert.equal(normalized.name, 'Pi Runtime')
  assert.equal(normalized.workspace, '/workspace')
  assert.equal(normalized.network.public_url, 'https://mcp.example.com')
  assert.deepEqual(normalized.oauth_password_update, { action: 'unchanged' })
})

test('serializes explicit secret replacements and clears', () => {
  const normalized = normalizedRuntimeDraft({
    ...draft,
    oauth_password: 'replacement',
    oauth_password_action: 'set',
    network: {
      provider: 'cloudflare',
      public_url: '',
      options: { executable: 'cloudflared', tunnel_token: '' },
      configured_secrets: ['tunnel_token'],
      secret_actions: { tunnel_token: 'clear' },
    },
  })
  assert.deepEqual(normalized.oauth_password_update, { action: 'set', value: 'replacement' })
  assert.deepEqual(normalized.network.secret_updates.tunnel_token, { action: 'clear' })
  assert.equal(normalized.network.options.executable, 'cloudflared')
})

test('shows the MCP URL only after the runtime has started successfully', () => {
  const runtime = {
    ...draft,
    runtime_id: 'default',
    has_oauth_password: false,
    remember_secrets: false,
    running: true,
    public_mcp_url: 'https://active.example.com/mcp',
    url_mode: 'External URL',
    exit_reason: '',
  } satisfies RuntimeDto
  assert.equal(runtimeUrl(runtime), 'https://active.example.com/mcp')
  assert.equal(runtimeUrl({ ...runtime, running: false }), '')
  assert.equal(runtimeUrl({ ...runtime, running: false, public_mcp_url: 'http://localhost:8123/mcp' }), '')
})
