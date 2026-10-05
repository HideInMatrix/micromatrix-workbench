import { execFileSync, spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'
import { cloudflaredManifest } from './prepare-cloudflared.mjs'

const root = process.cwd()
const expectedVersion = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version
const productName = JSON.parse(readFileSync(path.join(root, 'src-tauri/tauri.conf.json'), 'utf8')).productName

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
const bundled = process.argv.includes('--bundled')
if (bundled && process.platform !== 'darwin') throw new Error('--bundled currently verifies the macOS application bundle')
const executable = bundled
  ? path.join(root, 'src-tauri/target/release/bundle/macos', `${productName}.app`, 'Contents/MacOS/micromatrix-service')
  : path.join(root, 'src-tauri/binaries', `micromatrix-service-${nativeBuildTarget()}${extension}`)
const temporary = await mkdtemp(path.join(os.tmpdir(), 'micromatrix-sidecar-smoke-'))
const cloudflared = path.join(path.dirname(executable), bundled ? 'cloudflared' : `cloudflared-${nativeBuildTarget()}${extension}`)
try {
  const version = execFileSync(cloudflared, ['--version'], {
    encoding: 'utf8', timeout: 10_000, windowsHide: true,
    env: { ...process.env, PATH: temporary },
  })
  if (!version.includes(`version ${cloudflaredManifest.version} `)) throw new Error(`Unexpected bundled cloudflared: ${version}`)
  execFileSync(cloudflared, ['--no-autoupdate', 'tunnel', '--help'], {
    timeout: 10_000, windowsHide: true, stdio: 'ignore', env: { ...process.env, PATH: temporary },
  })
  console.log(`PASS: bundled cloudflared ${cloudflaredManifest.version} executes without a system PATH installation`)
} catch (error) {
  await rm(temporary, { recursive: true, force: true })
  throw error
}
const controlPort = await availablePort()
let runtimePort = await availablePort()
while (runtimePort === controlPort) runtimePort = await availablePort()
const baseUrl = `http://127.0.0.1:${controlPort}`
const output = []
const child = spawn(executable, [], {
  cwd: temporary,
  env: {
    ...process.env,
    PATH: temporary,
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

  const health = await fetch(`${baseUrl}/healthz`).then(response => response.json())
  if (health.process_id !== child.pid) throw new Error('Native shutdown cannot identify the owned service PID')
  const indexResponse = await fetch(`${baseUrl}/`)
  const index = await indexResponse.text()
  if (!indexResponse.ok || !index.includes(`<title>${productName}</title>`)) {
    throw new Error('Sidecar did not serve the embedded Vite application')
  }

  const bootstrapResponse = await fetch(`${baseUrl}/api/desktop`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ method: 'bootstrap', args: [] }),
  })
  const bootstrap = await bootstrapResponse.json()
  if (!bootstrapResponse.ok || bootstrap.app_name !== productName || bootstrap.version !== expectedVersion || bootstrap.runtime?.running !== false || bootstrap.runtime?.exit_reason !== '') {
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
  await assertReleased(`http://127.0.0.1:${runtimePort}/mcp`)

  // Exercise the public data plane only after an explicit start, using a
  // temporary workspace and the local External provider (no real Tunnel).
  async function command(method, args = []) {
    const response = await fetch(`${baseUrl}/api/desktop`, {
      method: 'POST',
      headers: { origin: baseUrl, 'content-type': 'application/json' },
      body: JSON.stringify({ method, args }),
      signal: AbortSignal.timeout(10_000),
    })
    const result = await response.json()
    if (!response.ok) throw new Error(`Smoke command ${method} failed: ${JSON.stringify(result)}`)
    return result
  }
  const cloudflareProtocol = bootstrap.network_providers?.find(provider => provider.key === 'cloudflare')
    ?.options.find(option => option.key === 'protocol')
  if (cloudflareProtocol?.default_value !== 'auto' ||
      JSON.stringify(cloudflareProtocol.choices.map(choice => choice.value)) !== JSON.stringify(['auto', 'http2', 'quic'])) {
    throw new Error('Cloudflare provider did not advertise its transport selector')
  }
  for (const protocol of ['auto', 'http2', 'quic']) {
    const configuredCloudflare = await command('configure_runtime', [{
      ...bootstrap.runtime, remember_secrets: false,
      network: { provider: 'cloudflare', public_url: '', options: { protocol } },
    }])
    const saved = JSON.parse(readFileSync(path.join(temporary, 'runtime.json'), 'utf8'))
    if (configuredCloudflare.running !== false || configuredCloudflare.network?.options?.protocol !== protocol ||
        saved.network?.options?.protocol !== protocol) {
      throw new Error(`Cloudflare transport ${protocol} did not persist without auto-starting`)
    }
    await assertReleased(`http://127.0.0.1:${runtimePort}/`)
  }
  console.log('PASS: Cloudflare auto/http2/quic selector persists all choices without starting any Tunnel')
  const runtimeUrl = `http://127.0.0.1:${runtimePort}`
  const configured = await command('configure_runtime', [{
    ...bootstrap.runtime,
    oauth_password_update: { action: 'set', value: 'smoke-only-private-password' },
    network: { provider: 'external', public_url: runtimeUrl, options: {} },
    remember_secrets: false,
  }])
  if (configured.running !== false) throw new Error('Configuration unexpectedly started the runtime')
  await command('create_pi_skill', ['smoke', 'SEA Pi resource discovery smoke test', 'marker=pi_resource_in_sea'])
  const idleExtensions = await command('get_pi_extensions')
  if (idleExtensions.host_active !== false || idleExtensions.configuration.skills.length !== 1 || idleExtensions.loaded_skills.length !== 0) {
    throw new Error('Saving a Pi Skill unexpectedly started its extension host')
  }
  const document = await command('read_pi_skill_document', ['smoke'])
  await command('edit_pi_skill_document', ['smoke', document.document.replace('pi_resource_in_sea', 'pi_edited_resource_in_sea'), document.revision])
  await writeFile(path.join(temporary, 'skills/smoke/guide.md'), 'SEA support file marker')
  const editedDocument = await command('read_pi_skill_document', ['smoke'])
  if (!editedDocument.document.includes('pi_edited_resource_in_sea') || !editedDocument.files.some(file => file.path === 'guide.md')) throw new Error('Packaged Skill editor/support-file discovery failed')
  const fixturePath = path.join(temporary, 'mcp-fixture.mjs')
  const pidPath = path.join(temporary, 'mcp-pid.txt')
  const sdk = file => JSON.stringify(pathToFileURL(path.join(root, 'node_modules/@modelcontextprotocol/sdk/dist/esm', file)).href)
  await writeFile(fixturePath, `import {Server} from ${sdk('server/index.js')};import{StdioServerTransport}from ${sdk('server/stdio.js')};import{ListToolsRequestSchema}from ${sdk('types.js')};import{writeFileSync}from'node:fs';writeFileSync(${JSON.stringify(pidPath)},String(process.pid));const server=new Server({name:'SEA fixture',version:'1'},{capabilities:{tools:{}}});server.setRequestHandler(ListToolsRequestSchema,()=>{if(process.env.MCP_SMOKE_SECRET!=='sea-fixture-private-value')throw Error('missing credential');return{tools:[{name:'fixture',description:'SEA bridge fixture',inputSchema:{type:'object',properties:{}}}]}});await server.connect(new StdioServerTransport());`)
  const connection = { id: 'fixture', name: 'SEA fixture', enabled: true, transport: 'stdio', command: process.execPath, args: [fixturePath], envRefs: { MCP_SMOKE_SECRET: 'SMOKE_SECRET' } }
  await command('configure_pi_extensions', [{ ...idleExtensions.configuration, mcp: [connection] }])
  await command('set_pi_mcp_credentials', ['fixture', { SMOKE_SECRET: 'sea-fixture-private-value' }])
  const savedExtensions = await command('get_pi_extensions')
  if (JSON.stringify(savedExtensions).includes('sea-fixture-private-value') || savedExtensions.host_active) throw new Error('Credential save exposed a value or auto-started Pi')
  const tested = await command('test_pi_mcp', [connection])
  if (JSON.stringify(tested.tools) !== '["fixture"]') throw new Error('Packaged MCP client discovery or local credential injection failed')
  async function assertFixtureExited() {
    const pid = Number(readFileSync(pidPath, 'utf8'))
    for (let i = 0; i < 30; i++) {
      try { process.kill(pid, 0) } catch { return }
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    throw new Error('Packaged MCP child was not cleaned up')
  }
  await assertFixtureExited()
  await assertReleased(`${runtimeUrl}/`)
  const started = await command('start_runtime')
  if (started.running !== true) throw new Error('Explicit runtime start failed')
  const activeExtensions = await command('get_pi_extensions')
  if (activeExtensions.host_active !== true || activeExtensions.loaded_skills[0]?.id !== 'smoke') {
    throw new Error('SEA did not load the official Pi extension host and Skill resource')
  }
  const cardResponse = await fetch(`${runtimeUrl}/`)
  const card = await cardResponse.json()
  if (!cardResponse.ok || card.server?.name !== productName || card.server?.version !== expectedVersion ||
      card.transport?.endpoint !== '/mcp' || card.transport?.type !== 'streamable_http' ||
      card.auth?.type !== 'oauth2' || !card.tools?.names?.includes('read') || card.tools.count !== card.tools.names.length) {
    throw new Error(`Unexpected public MCP server card: ${JSON.stringify(card)}`)
  }
  if (!card.tools.names.includes('skills_read') || !card.tools.names.includes('skills_list') || !card.tools.names.includes('skills_file_read') || !card.tools.names.some(name => name.startsWith('mcp__fixture__'))) {
    throw new Error('Pi registered Skill tools were not exposed by the packaged MCP service')
  }
  if (JSON.stringify(card).includes(temporary) || JSON.stringify(card).includes('smoke-only-private-password')) {
    throw new Error('Public MCP server card exposed private configuration')
  }
  const denied = await fetch(`${runtimeUrl}/mcp`, { method: 'POST' })
  if (denied.status !== 401) throw new Error('Public server card bypassed MCP authentication')
  const oauthMetadata = await fetch(`${runtimeUrl}/.well-known/oauth-authorization-server`).then(response => response.json())
  if (oauthMetadata.client_id_metadata_document_supported !== true || oauthMetadata.authorization_response_iss_parameter_supported !== true ||
      oauthMetadata.registration_endpoint !== undefined || JSON.stringify(oauthMetadata.token_endpoint_auth_methods_supported) !== '["none"]') {
    throw new Error('Packaged OAuth did not advertise CIMD, issuer identification and no registration endpoint')
  }
  if ((await fetch(`${runtimeUrl}/register`, { method: 'POST', body: '{}' })).status !== 404) throw new Error('Removed DCR endpoint is still reachable')
  const unsafeClient = await fetch(`${runtimeUrl}/authorize?${new URLSearchParams({
    client_id: 'https://127.0.0.1/private', redirect_uri: 'https://client.example/callback',
    response_type: 'code', code_challenge_method: 'S256', code_challenge: 'x'.repeat(43),
  })}`, { redirect: 'manual' })
  if (unsafeClient.status !== 400 || unsafeClient.headers.has('location') || (await unsafeClient.json()).error !== 'invalid_client_metadata') {
    throw new Error('Packaged CIMD accepted a private metadata destination')
  }
  console.log('PASS: packaged OAuth is CIMD-only; unsafe metadata URLs are refused without a redirect')
  const stopped = await command('stop_runtime')
  if (stopped.running !== false) throw new Error('Explicit runtime stop failed')
  const stoppedExtensions = await command('get_pi_extensions')
  if (stoppedExtensions.host_active !== false || stoppedExtensions.loaded_skills.length !== 0) {
    throw new Error('Pi extension resources survived Runtime shutdown')
  }
  await assertReleased(`${runtimeUrl}/`)
  await assertFixtureExited()
  console.log('PASS: packaged MCP stdio bridge resolves local credentials, registers real discovered tools, and closes test/runtime children')
  console.log('PASS: manual start exposes a safe public MCP server card; MCP stays protected and stop releases its port')
  console.log('PASS: packaged Pi ExtensionFactory/ResourceLoader loads Skills only on explicit start and clears them on stop')

  child.kill('SIGTERM')
  const exit = await waitForExit(child)
  // Windows child.kill forcibly terminates the process; it cannot certify the
  // Unix SIGTERM cleanup path. Still assert that its listener is released.
  if (process.platform !== 'win32' && exit.code !== 0) throw new Error(`Sidecar exited abnormally: ${JSON.stringify(exit)}\n${output.join('')}`)
  await assertReleased(`${baseUrl}/healthz`)
  console.log(`PASS: ${path.relative(root, executable)} reported version ${expectedVersion}, served embedded UI/API and released its control port (${process.platform === 'win32' ? 'forced Windows termination' : 'graceful SIGTERM'})`)
} finally {
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL')
    await waitForExit(child).catch(() => undefined)
  }
  await rm(temporary, { recursive: true, force: true })
}
