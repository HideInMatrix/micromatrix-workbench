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
} finally {
  await browser?.close()
  if (child && child.exitCode === null && child.signalCode === null) {
    const exited = once(child, 'exit'); child.kill('SIGTERM')
    const kill = setTimeout(() => child.kill('SIGKILL'), 10000)
    try { await exited } finally { clearTimeout(kill) }
  }
  await rm(directory, { recursive: true, force: true })
}
