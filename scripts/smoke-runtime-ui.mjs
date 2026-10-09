import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { once } from 'node:events'
import os from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright-core'

// The real bundled web app and real control plane, with a fresh workspace and
// disposable browser. No access to the user's browser profile or Runtime.
const flag = process.argv.indexOf('--browser-executable')
const executablePath = flag < 0 ? undefined : process.argv[flag + 1]
if (flag >= 0 && (!executablePath || !path.isAbsolute(executablePath))) throw Error('An absolute owned-test browser executable is required')
const directory = await mkdtemp(path.join(os.tmpdir(), 'mm-runtime-ui-'))
const reservation = createServer(); reservation.listen(0, '127.0.0.1'); await once(reservation, 'listening')
const port = reservation.address().port; await new Promise(resolve => reservation.close(resolve))
const base = `http://127.0.0.1:${port}`
let browser, child, output = ''
try {
  child = spawn(process.execPath, ['dist/micromatrix-service.cjs'], { env: { ...process.env,
    MICROMATRIX_CONFIG_FILE: path.join(directory, 'runtime.json'), MICROMATRIX_WORKSPACE: directory,
    MICROMATRIX_CONTROL_PORT: String(port), MICROMATRIX_CONTROL_HOST: '127.0.0.1',
    MICROMATRIX_NETWORK_PROVIDER: 'frp', MICROMATRIX_PORT: String(port === 65535 ? port - 1 : port + 1),
    MICROMATRIX_OAUTH_PASSWORD: '', MICROMATRIX_TUNNEL_TOKEN: '', MICROMATRIX_AUTO_START: 'false',
  }, stdio: ['ignore', 'pipe', 'pipe'] })
  for (const stream of [child.stdout, child.stderr]) stream.on('data', data => { output = (output + data).slice(-16000) })
  let ready = false
  for (let i = 0; i < 150; i++) {
    if (child.exitCode !== null) throw Error(`Fixture service exited: ${output}`)
    try { ready = (await fetch(base + '/healthz', { signal: AbortSignal.timeout(500) })).ok } catch {}
    if (ready) break
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  assert.ok(ready, output)
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
  const page = await browser.newPage({ viewport: { width: 1180, height: 840 } })
  const commands = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    if (request.url().endsWith('/api/desktop')) {
      const body = request.postDataJSON(); if (body?.method) commands.push(body.method)
    }
  })
  await page.goto(base + '/#/plugins')
  const card = page.getByRole('region', { name: '内置 Computer Use' })
  await card.waitFor(); await page.locator('#computer-browser-endpoint').waitFor({ state: 'attached' })
  await card.locator('summary').click()
  const endpoint = 'ws://127.0.0.1:9222/devtools/browser/fixture'
  await page.locator('#computer-browser-endpoint').fill(endpoint)
  await page.locator('#computer-browser-origins').fill('https://example.com\nhttps://example.org\nhttps://example.com')
  await card.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('浏览器配置已保存', { exact: true }).waitFor()
  const config = JSON.parse(await readFile(path.join(directory, 'runtime.json'), 'utf8'))
  assert.deepEqual(config.computerUse.browser, { endpoint, allowedOrigins: ['https://example.com', 'https://example.org'] })
  await page.reload(); await card.waitFor(); await card.locator('summary').click()
  await page.waitForFunction(endpoint => document.querySelector('#computer-browser-endpoint')?.value === endpoint, endpoint)
  assert.equal(await page.locator('#computer-browser-origins').inputValue(), 'https://example.com\nhttps://example.org')
  await page.locator('#computer-browser-endpoint').fill('ws://outside.example/devtools/browser/not-local')
  await card.getByRole('button', { name: '保存', exact: true }).click()
  await card.getByRole('alert', { name: '浏览器配置错误' }).waitFor()
  assert.equal(await page.locator('#computer-browser-endpoint').inputValue(), 'ws://outside.example/devtools/browser/not-local', 'Rejected save must preserve the user draft')
  assert.equal(JSON.parse(await readFile(path.join(directory, 'runtime.json'), 'utf8')).computerUse.browser.endpoint, endpoint)
  await card.getByRole('button', { name: '关闭通道', exact: true }).click()
  await page.getByText('已关闭浏览器通道', { exact: true }).waitFor()
  assert.equal(await page.locator('#computer-browser-endpoint').inputValue(), '')
  assert.equal(JSON.parse(await readFile(path.join(directory, 'runtime.json'), 'utf8')).computerUse.browser, undefined)
  const result = await fetch(base + '/api/desktop', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ method: 'get_runtime', args: [] }) })
  assert.ok(result.ok); const services = await result.json(); assert.equal(services.running, false)
  assert.ok(!commands.some(command => ['start_runtime', 'check_computer_use_permissions', 'open_computer_use_settings'].includes(command)))
  assert.deepEqual(errors, [])
  if (process.env.MM_SMOKE_UI_SCREENSHOT) {
    assert.ok(path.isAbsolute(process.env.MM_SMOKE_UI_SCREENSHOT), 'QA screenshot path must be absolute')
    await page.screenshot({ path: process.env.MM_SMOKE_UI_SCREENSHOT })
  }
  console.log('PASS: real packaged Vue UI + control service: save/deduplicate/persist/reload, reject remote endpoint without losing draft, clear, no Runtime/helper/browser startup')

  // Loopback API contract fixture: hold Start like an unreachable public health
  // check. Keep the real bundled UI; never start the user's or fixture's tunnel.
  let releaseStart, notifyStart, startRequested = false, stopRequested = false
  const heldStart = new Promise(resolve => { releaseStart = resolve })
  const startArrived = new Promise(resolve => { notifyStart = resolve })
  await page.route(base + '/api/desktop', async route => {
    const method = route.request().postDataJSON()?.method
    if (method === 'configure_runtime' || method === 'stop_runtime') {
      if (method === 'stop_runtime') stopRequested = true
      await route.fulfill({ json: services })
      if (method === 'stop_runtime') releaseStart()
    } else if (method === 'start_runtime') {
      startRequested = true
      notifyStart()
      await heldStart
      // Cancellation aborts this browser request; tolerate that closed route.
      try { await route.fulfill({ json: { ...services, running: true } }) } catch {}
    } else await route.continue()
  })
  await page.goto(base + '/#/runtime')
  await page.getByRole('button', { name: '启动', exact: true }).click()
  const cancel = page.getByRole('button', { name: '取消启动', exact: true })
  await cancel.waitFor(); assert.equal(await cancel.isEnabled(), true)
  await startArrived
  await cancel.click()
  await page.getByText('Runtime 已停止。', { exact: true }).waitFor()
  await page.getByRole('button', { name: '启动', exact: true }).waitFor()
  assert.ok(startRequested && stopRequested)
  assert.deepEqual(errors, [])
  console.log('PASS: bundled Runtime UI cancels held startup via local Stop, unlocks controls and ignores late startup success (API contract fixture, not physical WAN disconnect)')

  // Exercise the production About UI with an owned native-bridge contract.
  // Intercept the native loopback port before navigation: never call the user's
  // installed service, updater, settings, or application restart.
  const nativePage = await browser.newPage({ viewport: { width: 1180, height: 840 } })
  nativePage.on('pageerror', error => errors.push(error.message))
  const installation = []
  await nativePage.route('http://127.0.0.1:8233/**', async route => {
    const request = route.request()
    const headers = { 'access-control-allow-origin': base, 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type' }
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    if (request.postDataJSON()?.method === 'stop_runtime') installation.push('stop_runtime')
    const response = await fetch(base + new URL(request.url()).pathname, { method: request.method(), ...(request.postData() ? { body: request.postData(), headers: { 'content-type': 'application/json' } } : {}) })
    await route.fulfill({ status: response.status, body: await response.text(), headers: { ...headers, 'content-type': 'application/json' } })
  })
  await nativePage.exposeFunction('recordUpdateAction', command => installation.push(command))
  await nativePage.addInitScript(() => {
    window.isTauri = true
    window.updateFixture = { prefix: 'https://cdn.gh-proxy.org/', calls: [], callbacks: 0 }
    window.__TAURI_INTERNALS__ = {
      transformCallback: () => ++window.updateFixture.callbacks,
      unregisterCallback() {},
      async invoke(command, args) {
        const fixture = window.updateFixture; fixture.calls.push(command)
        if (command === 'get_update_preferences') return { download_proxy_prefix: fixture.prefix }
        if (command === 'save_update_preferences') {
          fixture.prefix = args.prefix.trim() ? args.prefix.trim().replace(/\/+$/, '') + '/' : ''
          return { download_proxy_prefix: fixture.prefix }
        }
        if (command === 'check_update_with_prefix') return { rid: 1, currentVersion: '0.5.24', version: '99.0.0', body: 'Owned fixture release', rawJson: {} }
        if (command === 'plugin:app|version') return '0.5.24'
        if (command === 'desktop_service_error' || command === 'runtime_saved_secrets') return null
        if (command === 'plugin:resources|close') return
        if (['plugin:updater|download', 'plugin:updater|install', 'plugin:process|restart'].includes(command)) {
          await window.recordUpdateAction(command)
          return command === 'plugin:updater|download' ? 2 : undefined
        }
        throw Error(`Unexpected native fixture command: ${command}`)
      },
    }
  })
  await nativePage.goto(base + '/#/about')
  const install = nativePage.getByRole('button', { name: '下载更新并重启', exact: true })
  await install.waitFor()
  assert.deepEqual(installation, [], 'Background check must never download, stop, install or restart')
  const prefix = nativePage.getByPlaceholder('留空则直连 GitHub')
  assert.equal(await prefix.inputValue(), 'https://cdn.gh-proxy.org/')
  await prefix.fill('')
  await nativePage.getByRole('button', { name: '保存前缀', exact: true }).click()
  await nativePage.getByText('下载加速前缀已保存。', { exact: true }).waitFor()
  assert.equal(await nativePage.evaluate(() => window.updateFixture.prefix), '')
  await install.waitFor({ state: 'detached' })
  await prefix.fill('https://mirror.example/base')
  await nativePage.getByRole('button', { name: '保存前缀', exact: true }).click()
  await nativePage.waitForFunction(() => document.querySelector('input[placeholder="留空则直连 GitHub"]')?.value === 'https://mirror.example/base/')
  await nativePage.getByRole('button', { name: '检查更新', exact: true }).click()
  await install.waitFor()
  assert.deepEqual(installation, [])
  assert.ok((await nativePage.evaluate(() => window.updateFixture.calls)).includes('plugin:resources|close'), 'Changing the prefix must release the old native update resource')
  await install.click()
  await nativePage.getByText('更新已安装，重启应用后生效。', { exact: true }).waitFor()
  assert.deepEqual(installation, ['plugin:updater|download', 'stop_runtime', 'plugin:updater|install', 'plugin:process|restart'])
  assert.deepEqual(errors, [])
  console.log('PASS: bundled About UI checks without installation, saves direct/custom prefix, invalidates old resources, installs/restarts only after click (native bridge contract, not a signed installer test)')
} finally {
  await browser?.close()
  if (child && child.exitCode === null && child.signalCode === null) {
    const exited = once(child, 'exit'); child.kill('SIGTERM')
    const kill = setTimeout(() => child.kill('SIGKILL'), 10000)
    try { await exited } finally { clearTimeout(kill) }
  }
  await rm(directory, { recursive: true, force: true })
}
