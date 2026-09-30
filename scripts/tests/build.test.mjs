import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

const root = path.resolve(import.meta.dirname, '../..')

test('prebuilt-web rejects missing or empty artifacts instead of silently rebuilding', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'mm-prebuilt-web-'))
  try {
    for (const emptyIndex of [false, true]) {
      if (emptyIndex) {
        mkdirSync(path.join(directory, 'apps/web/dist'), { recursive: true })
        writeFileSync(path.join(directory, 'apps/web/dist/index.html'), '  \n')
      }
      const result = spawnSync(process.execPath, [path.join(root, 'scripts/build-service.mjs'), '--prebuilt-web'], {
        cwd: directory, encoding: 'utf8', timeout: 10_000,
      })
      assert.ifError(result.error)
      assert.equal(result.status, 1)
      assert.match(result.stderr, /--prebuilt-web requires a non-empty apps\/web\/dist\/index.html/)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test('Tauri prebuilt override disables only the frontend build hook', () => {
  const normal = JSON.parse(readFileSync(path.join(root, 'src-tauri/tauri.conf.json'), 'utf8'))
  const prebuilt = JSON.parse(readFileSync(path.join(root, 'src-tauri/tauri.prebuilt.conf.json'), 'utf8'))
  assert.equal(normal.build.beforeBuildCommand, 'npm run build:web')
  assert.deepEqual(prebuilt.build, { beforeBuildCommand: null })
  assert.deepEqual(Object.keys(prebuilt).sort(), ['$schema', 'build'])
})
