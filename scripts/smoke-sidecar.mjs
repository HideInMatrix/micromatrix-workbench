import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { nativeBuildTarget } from './build-platform.mjs'

const root = process.cwd()

async function availablePort() {
  const server = net.createServer()
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const port = typeof address === 'object' && address ? address.port : 0
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  if (!port) throw new Error('Failed to reserve a loopback port')
  return port
}

async function waitForHealth(url, child, output, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Sidecar exited before becoming healthy\n${output.join('')}`)
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1_000) })
      if (response.ok && (await response.json()).ok === true) return
    } catch {
      // SEA startup can take several seconds; retry until the bounded deadline.
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error(`Sidecar health check timed out after ${timeoutMs}ms\n${output.join('')}`)
}

async function waitForExit(child, timeoutMs = 10_000) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return { code: child.exitCode, signal: child.signalCode }
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      reject(new Error(`Sidecar did not exit within ${timeoutMs}ms after SIGTERM`))
    }, timeoutMs)
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      resolve({ code, signal })
    })
  })
}

async function assertReleased(url) {
  try {
    await fetch(url, { signal: AbortSignal.timeout(500) })
  } catch {
    return
  }
  throw new Error('Sidecar control port remained reachable after shutdown')
}

const extension = process.platform === 'win32' ? '.exe' : ''
const executable = path.join(root, 'src-tauri/binaries', `micromatrix-service-${nativeBuildTarget()}${extension}`)
const temporary = await mkdtemp(path.join(os.tmpdir(), 'micromatrix-sidecar-smoke-'))
const controlPort = await availablePort()
let runtimePort = await availablePort()
while (runtimePort === controlPort) runtimePort = await availablePort()
const baseUrl = `http://127.0.0.1:${controlPort}`
const output = []
const child = spawn(executable, [], {
  cwd: root,
  env: {
    ...process.env,
    MICROMATRIX_CONFIG_FILE: path.join(temporary, 'runtime.json'),
    MICROMATRIX_WORKSPACE: temporary,
    MICROMATRIX_CONTROL_HOST: '127.0.0.1',
    MICROMATRIX_CONTROL_PORT: String(controlPort),
    MICROMATRIX_HOST: '127.0.0.1',
    MICROMATRIX_PORT: String(runtimePort),
    // An old auto-start preference plus incomplete provider configuration must
    // still boot idle and expose the repair/configuration UI.
    MICROMATRIX_ENABLED: 'true',
    MICROMATRIX_NETWORK_PROVIDER: 'frp',
    MICROMATRIX_PUBLIC_URL: '',
    MICROMATRIX_OAUTH_PASSWORD: '',
    MICROMATRIX_AUTH_TOKEN: '',
    MICROMATRIX_REMEMBER_SECRETS: 'false',
    MICROMATRIX_ENABLE_SHELL: 'false',
    MICROMATRIX_FRP_CONFIG: '',
  },
  stdio: ['ignore', 'pipe', 'pipe'],
})
child.stdout.setEncoding('utf8').on('data', chunk => output.push(chunk))
child.stderr.setEncoding('utf8').on('data', chunk => output.push(chunk))

try {
  await waitForHealth(`${baseUrl}/healthz`, child, output)

  const indexResponse = await fetch(`${baseUrl}/`)
  const index = await indexResponse.text()
  if (!indexResponse.ok || !index.includes('<title>MicroMatrix Workbench</title>')) {
    throw new Error('Sidecar did not serve the embedded Vite application')
  }

  const bootstrapResponse = await fetch(`${baseUrl}/api/desktop`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ method: 'bootstrap', args: [] }),
  })
  const bootstrap = await bootstrapResponse.json()
  if (!bootstrapResponse.ok || bootstrap.app_name !== 'MicroMatrix Pi MCP' || bootstrap.runtime?.running !== false || bootstrap.runtime?.exit_reason !== '') {
    throw new Error(`Unexpected bootstrap response: ${JSON.stringify(bootstrap)}`)
  }

  const sameOriginResponse = await fetch(`${baseUrl}/api/desktop`, {
    method: 'POST',
    headers: { origin: baseUrl, 'content-type': 'application/json' },
    body: JSON.stringify({ method: 'bootstrap', args: [] }),
  })
  if (!sameOriginResponse.ok) throw new Error('Embedded browser Origin was rejected by the control API')
  const sameOrigin = await sameOriginResponse.json()
  if (sameOrigin.runtime?.running !== false) throw new Error('Sidecar unexpectedly auto-started the runtime')

  child.kill('SIGTERM')
  const exit = await waitForExit(child)
  // Windows child.kill forcibly terminates the process; it cannot certify the
  // Unix SIGTERM cleanup path. Still assert that its listener is released.
  if (process.platform !== 'win32' && exit.code !== 0) throw new Error(`Sidecar exited abnormally: ${JSON.stringify(exit)}\n${output.join('')}`)
  await assertReleased(`${baseUrl}/healthz`)
  console.log(`PASS: ${path.relative(root, executable)} served embedded UI/API and released its control port (${process.platform === 'win32' ? 'forced Windows termination' : 'graceful SIGTERM'})`)
} finally {
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL')
    await waitForExit(child).catch(() => undefined)
  }
  await rm(temporary, { recursive: true, force: true })
}
