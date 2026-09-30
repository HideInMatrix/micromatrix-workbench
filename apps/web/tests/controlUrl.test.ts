import assert from 'node:assert/strict'
import test from 'node:test'
import { controlBaseUrl } from '../src/api/controlUrl.ts'

test('embedded production UI uses its own origin including a custom control port', () => {
  assert.equal(controlBaseUrl({ development: false, tauri: false, origin: 'http://127.0.0.1:19533' }), 'http://127.0.0.1:19533')
})

test('Vite and Tauri retain the separate loopback control endpoint', () => {
  assert.equal(controlBaseUrl({ development: true, tauri: false, origin: 'http://127.0.0.1:5173' }), 'http://127.0.0.1:8233')
  assert.equal(controlBaseUrl({ development: false, tauri: true, origin: 'tauri://localhost' }), 'http://127.0.0.1:8233')
})

test('explicit control URL overrides all defaults', () => {
  assert.equal(controlBaseUrl({ configured: 'http://localhost:19533/', development: true, tauri: true, origin: 'tauri://localhost' }), 'http://localhost:19533')
})
