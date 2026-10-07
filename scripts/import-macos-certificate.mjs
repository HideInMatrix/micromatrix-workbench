import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { buildChannel, macSigningIdentity, validateMacosCertificate } from './build-channel.mjs'

// Owned temporary keychain only; no login/default keychain or trust changes.
// CI imports once across job steps. Explicit local build/probe cleans in finally.
const action = process.argv[2]
const local = ['build', 'probe'].includes(action)
if (process.platform !== 'darwin' || (!local && (process.env.GITHUB_ACTIONS !== 'true' || !process.env.RUNNER_TEMP))) throw new Error('Use a macOS Actions runner, or explicit local build/probe')
const env = { ...process.env }
if (local) {
  const directory = path.resolve('.local/macos-signing')
  Object.assign(env, JSON.parse(readFileSync(path.join(directory, 'variables.json'), 'utf8')), {
    MICROMATRIX_BUILD_CHANNEL: 'release',
    APPLE_CERTIFICATE: readFileSync(path.join(directory, 'certificate.p12')).toString('base64'),
    APPLE_CERTIFICATE_PASSWORD: readFileSync(path.join(directory, 'password.txt'), 'utf8'),
  })
  macSigningIdentity(env)
}
const temporary = local ? mkdtempSync(path.join(os.tmpdir(), 'mm-local-signing-')) : path.resolve(env.RUNNER_TEMP)
const stateFile = path.join(temporary, 'micromatrix-apple-signing.json')
const security = (...args) => execFileSync('/usr/bin/security', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })

function cleanup() {
  if (!existsSync(stateFile)) return
  const state = JSON.parse(readFileSync(stateFile, 'utf8'))
  if (path.dirname(state.directory) !== temporary || !path.basename(state.directory).startsWith('mm-apple-')
    || state.keychain !== path.join(state.directory, 'build.keychain-db') || !Array.isArray(state.previous)) throw new Error('Invalid owned keychain state')
  let failed = false
  try { security('list-keychains', '-d', 'user', '-s', ...state.previous) } catch { failed = true }
  if (existsSync(state.keychain)) try { security('delete-keychain', state.keychain) } catch { failed = true }
  if (failed) throw new Error('Temporary Apple keychain cleanup failed')
  rmSync(state.directory, { recursive: true, force: true })
  rmSync(stateFile)
}

if (action === 'cleanup') {
  cleanup()
} else if (action === 'import' || local) {
  if (buildChannel(env) !== 'release') throw new Error('Only release builds import the long-lived certificate')
  macSigningIdentity(env)
  if (existsSync(stateFile)) throw new Error('Owned signing keychain already exists; cleanup before retrying')
  const encoded = env.APPLE_CERTIFICATE || ''
  if (!encoded || encoded.length > 2 * 1024 * 1024) throw new Error('Missing or oversized APPLE_CERTIFICATE')
  const directory = mkdtempSync(path.join(temporary, 'mm-apple-'))
  const keychain = path.join(directory, 'build.keychain-db')
  const certificate = path.join(directory, 'certificate.p12')
  let stage = 'read search list'
  try {
    const previous = security('list-keychains', '-d', 'user').split('\n').map(line => /^\s*"(.*)"\s*$/.exec(line)?.[1]).filter(Boolean)
    writeFileSync(stateFile, JSON.stringify({ directory, keychain, previous }), { mode: 0o600, flag: 'wx' })
    const password = randomBytes(32).toString('hex')
    if (!local) console.log(`::add-mask::${password}`)
    writeFileSync(certificate, Buffer.from(encoded, 'base64'), { mode: 0o600, flag: 'wx' })
    stage = 'verify pinned public certificate'
    const pem = execFileSync('/usr/bin/openssl', ['pkcs12', '-in', certificate, '-clcerts', '-nokeys', '-passin', 'env:APPLE_CERTIFICATE_PASSWORD'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env: { ...env, APPLE_CERTIFICATE_PASSWORD: env.APPLE_CERTIFICATE_PASSWORD || '' },
    })
    validateMacosCertificate(pem, env)
    stage = 'create temporary keychain'; security('create-keychain', '-p', password, keychain)
    security('set-keychain-settings', '-lut', '7200', keychain)
    security('unlock-keychain', '-p', password, keychain)
    stage = 'import certificate'; security('import', certificate, '-k', keychain, '-P', env.APPLE_CERTIFICATE_PASSWORD || '', '-T', '/usr/bin/codesign')
    stage = 'configure signing access'; security('set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, keychain)
    security('list-keychains', '-d', 'user', '-s', keychain, ...previous)
    stage = 'validate signing identity'
    // Self-signed roots are not Apple-trusted. Find the exact certificate/key,
    // not only system-trusted identities; never add a global trusted root.
    if (!security('find-identity', '-p', 'codesigning', keychain).toUpperCase().includes(env.APPLE_SIGNING_CERTIFICATE_SHA1.toUpperCase())) throw new Error('Identity unavailable')
    console.log('Prepared temporary pinned code-signing keychain; system trust unchanged')
  } catch (error) {
    try { cleanup() } catch { /* Always-step retries cleanup; do not expose commands/passwords. */ }
    if (!existsSync(stateFile)) rmSync(directory, { recursive: true, force: true })
    // Import errors contain format diagnostics, not key material. Never expose
    // execFile's message/arguments (which include passwords).
    const diagnostic = stage === 'import certificate' ? String(error.stderr || '').replaceAll(env.APPLE_CERTIFICATE_PASSWORD || '\0', '[redacted]').trim().slice(0, 400) : ''
    if (local && !existsSync(stateFile)) rmSync(temporary, { recursive: true, force: true })
    throw new Error(`Apple certificate setup failed at: ${stage}${diagnostic ? ` (${diagnostic})` : ''}`)
  } finally { rmSync(certificate, { force: true }) }
  if (local) {
    // Keep p12/password out of Tauri's implicit import path and child environment.
    delete env.APPLE_CERTIFICATE; delete env.APPLE_CERTIFICATE_PASSWORD
    delete env.APPLE_ID; delete env.APPLE_PASSWORD; delete env.APPLE_TEAM_ID
    delete env.APPLE_API_KEY; delete env.APPLE_API_ISSUER; delete env.APPLE_API_KEY_PATH
    try {
      execFileSync(process.execPath, [action === 'probe' ? 'scripts/smoke-macos-signing.mjs' : 'scripts/build-desktop.mjs', ...(action === 'build' ? process.argv.slice(3) : [])], { stdio: 'inherit', env })
    } finally {
      cleanup()
      rmSync(temporary, { recursive: true, force: true })
    }
  }
} else {
  throw new Error('Use import/cleanup in CI, or build/probe locally')
}
