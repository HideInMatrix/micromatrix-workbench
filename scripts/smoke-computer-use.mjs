import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { nativeBuildTarget } from './build-platform.mjs'

// The same packaged service is also a model-free stdio MCP. Exercise it in a
// disposable directory: never alter the installed app or request OS permission.
export async function smokeComputerUse(executable) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'micromatrix-computer-smoke-'))
  const marker = randomUUID()
  const client = new Client({ name: 'packaged-computer-use-smoke', version: '1' })
  const transport = new StdioClientTransport({
    command: executable, args: ['--computer-use-mcp', '--allow-actions'],
    cwd: directory, stderr: 'pipe', env: { ...process.env, PATH: directory },
  })
  let stderr = ''
  transport.stderr?.on('data', bytes => { stderr = (stderr + String(bytes)).slice(-4096) })
  async function call(name, args = {}) {
    const result = await client.callTool({ name, arguments: args }, undefined, { timeout: 15_000 })
    if (result.isError) throw new Error(`Computer Use ${name} failed: ${JSON.stringify(result.content)}`)
    return JSON.parse(result.content[0].text)
  }
  try {
    await writeFile(path.join(directory, 'input.json'), JSON.stringify({ marker, status: 'pending' }))
    await client.connect(transport)
    assert.equal((await client.listTools()).tools.length, 7)
    const capabilities = await call('computer_capabilities')
    assert.equal(capabilities.actions_enabled, true)
    const desktop = capabilities.adapters.find(adapter => adapter.id === 'desktop')
    assert.equal(desktop.available, true)
    const permissions = await call('computer_permissions', { request: false })
    if (process.platform === 'darwin') {
      assert.equal(permissions.bundle_id, 'org.micromatrix.computer-use')
      assert.match(permissions.helper_path, /micromatrix Computer Use\.app$/)
      assert.ok(['certificate', 'ad-hoc'].includes(permissions.signing_mode))
      assert.equal(permissions.prompt_requested, false)
      assert.equal(permissions.requires_screen_recording, false)
      const targets = await call('computer_targets')
      assert.ok(Array.isArray(targets.desktop))
      if (!permissions.accessibility && targets.desktop.length) {
        const denied = await client.callTool({ name: 'computer_observe', arguments: { adapter: 'desktop', target: targets.desktop[0].target } })
        assert.equal(denied.isError, true)
        assert.match(JSON.stringify(denied.content), /ACCESSIBILITY_PERMISSION_REQUIRED/)
      }
      console.log(`PASS: packaged macOS Computer Use.app, Accessibility=${permissions.accessibility}; no permission prompt or desktop action`)
    } else {
      assert.equal(permissions.platform, 'windows')
      assert.equal(permissions.supported, true)
      assert.equal(permissions.prompt_requested, false)
      assert.equal(typeof permissions.interactive_desktop, 'boolean')
      const targets = await call('computer_targets')
      assert.ok(Array.isArray(targets.desktop))
      if (!permissions.interactive_desktop) {
        const denied = await client.callTool({name:'computer_observe',arguments:{adapter:'desktop',target:'pid:1'}})
        assert.equal(denied.isError, true)
        assert.match(JSON.stringify(denied.content), /DESKTOP_ACCESS_REQUIRED/)
      }
      console.log('PASS: packaged Windows UIA helper, permission/desktop check; no elevation or desktop action')
    }
    const observed = await call('computer_observe', { adapter: 'json', target: 'input.json' })
    const action = {
      observation_id: observed.meta.observation_id, action_type: 'modify_file',
      target: 'json:/status', params: { value: 'passed' },
      expect_observation: { target: 'json:/status', value: 'passed' },
    }
    assert.equal((await call('computer_validate', action)).valid, true)
    assert.equal((await call('computer_act', action)).verification.status, 'passed')
    assert.deepEqual(JSON.parse(await readFile(path.join(directory, 'input.json'), 'utf8')), { marker, status: 'passed' })
    const replay = await client.callTool({ name: 'computer_act', arguments: action })
    assert.equal(replay.isError, true)
    assert.match(JSON.stringify(replay.content), /STALE_OBSERVATION/)
    assert.equal((await call('computer_trace')).length, 1)
    assert.doesNotMatch(stderr, /Desktop control plane listening/)
    console.log('PASS: packaged Computer Use stdio, semantic edit, independent verification and stale-action rejection')
  } finally {
    await client.close()
    await transport.close()
    await rm(directory, { recursive: true, force: true })
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const executable = path.resolve('src-tauri/binaries', `micromatrix-service-${nativeBuildTarget()}${process.platform === 'win32' ? '.exe' : ''}`)
  await smokeComputerUse(executable)
}
