import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cloneNetwork,
  emptyWorkDraft,
  normalizedWorkDraft,
} from '../src/components/services/serviceModels.ts'

test('new Cloudflare Work defaults to automatic tunnel transport', () => {
  const draft = emptyWorkDraft(8234)
  assert.equal(draft.network.options.tunnel_protocol, 'auto')
})

test('older Cloudflare settings display automatic transport without changing saved data', () => {
  const saved = { provider: 'cloudflare', public_url: '', options: {} }
  const copy = cloneNetwork(saved)

  assert.equal(copy.options.tunnel_protocol, 'auto')
  assert.deepEqual(saved.options, {})
})

test('chosen tunnel transport survives draft normalization', () => {
  const draft = emptyWorkDraft(8234)
  draft.network.options.tunnel_protocol = 'http2'
  draft.network.public_url = ' https://mcp.example.com/ '

  const normalized = normalizedWorkDraft(draft)
  assert.equal(normalized.network.options.tunnel_protocol, 'http2')
  assert.equal(normalized.network.public_url, 'https://mcp.example.com')
})
