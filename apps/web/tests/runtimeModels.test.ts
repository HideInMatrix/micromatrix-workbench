import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizedRuntimeDraft, runtimeUrl } from '../src/components/services/runtimeModels.ts'
import type { RuntimeDraft, RuntimeDto } from '../src/types.ts'

const draft: RuntimeDraft = {
  name: '  Pi Runtime  ',
  workspace: '  /workspace  ',
  oauth_password: '',
  host: '127.0.0.1',
  port: 8234,
  enabled: true,
  remember_secrets: false,
  permission_mode: 'safe',
  network: { provider: 'external', public_url: 'https://mcp.example.com///', options: {} },
}

test('normalizes the singleton runtime configuration', () => {
  const normalized = normalizedRuntimeDraft(draft)
  assert.equal(normalized.name, 'Pi Runtime')
  assert.equal(normalized.workspace, '/workspace')
  assert.equal(normalized.network.public_url, 'https://mcp.example.com')
})

test('prefers the active runtime MCP URL', () => {
  const runtime = {
    ...draft,
    runtime_id: 'default',
    oauth_password: '',
    has_saved_password: false,
    running: true,
    public_mcp_url: 'https://active.example.com/mcp',
    url_mode: 'External URL',
    exit_reason: '',
  } satisfies RuntimeDto
  assert.equal(runtimeUrl(runtime), 'https://active.example.com/mcp')
  assert.equal(runtimeUrl(draft), 'https://mcp.example.com/mcp')
})
