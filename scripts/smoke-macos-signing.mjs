import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { macSigningIdentity, macReleaseRequirement } from './build-channel.mjs'
import { verifyMacosSigning } from './verify-macos-signing.mjs'

// Real codesign regression; inert disposable bundles are NEVER launched or
// installed. This proves signature identity stability, not a granted TCC update.
if (process.platform !== 'darwin') throw new Error('Signing smoke requires macOS')
const identity = macSigningIdentity()
const temporary = mkdtempSync(path.join(os.tmpdir(), 'mm-signing-smoke-'))
const run = (args, options = {}) => execFileSync('/usr/bin/codesign', args, { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', ...options })
function bundle(application, identifier, version, designated = false) {
  const contents = path.join(application, 'Contents')
  mkdirSync(path.join(contents, 'MacOS'), { recursive: true })
  copyFileSync('/usr/bin/true', path.join(contents, 'MacOS/probe'))
  writeFileSync(path.join(contents, 'Info.plist'), `<?xml version="1.0"?><plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>${identifier}</string>
<key>CFBundleExecutable</key><string>probe</string>
<key>CFBundleVersion</key><string>${version}</string>
<key>CFBundlePackageType</key><string>APPL</string></dict></plist>`)
  const sign = () => run(['--force', '--sign', identity, '--options', 'runtime', '--timestamp=none',
    ...(designated ? ['--requirements', `=designated => ${macReleaseRequirement(process.env, identifier).slice(1)}`] : []), application])
  return sign
}
try {
  const snapshots = []
  for (const version of ['1.0.0', '1.0.1']) {
    const app = path.join(temporary, version, 'micromatrix agent.app')
    const signApp = bundle(app, 'org.micromatrix.pi-mcp', version)
    const helper = path.join(app, 'Contents/Helpers/micromatrix Computer Use.app')
    bundle(helper, 'org.micromatrix.computer-use', version, true)()
    // Tauri re-signs embedded apps with default codesign requirements. Check
    // that this still anchors the same certificate and survives packaging.
    run(['--force', '--sign', identity, '--options', 'runtime', helper])
    signApp()
    verifyMacosSigning(app)
    const details = spawnSync('/usr/bin/codesign', ['-d', '--verbose=4', helper], { encoding: 'utf8' })
    assert.equal(details.status, 0)
    const hash = /^CDHash=([a-f0-9]+)$/m.exec(details.stderr)?.[1]
    assert.ok(hash)
    snapshots.push({ dr: run(['-d', '-r-', helper]), hash })
    const wrong = { ...process.env, APPLE_SIGNING_CERTIFICATE_SHA1: '0'.repeat(40), APPLE_SIGNING_IDENTITY: '0'.repeat(40) }
    assert.throws(() => run(['--verify', '--test-requirement', macReleaseRequirement(wrong), helper]), 'a different certificate must fail')
    if (version === '1.0.1') {
      run(['--force', '--sign', '-', helper])
      assert.throws(() => verifyMacosSigning(app), 'ad-hoc or modified nested code must fail')
    }
  }
  assert.equal(snapshots[0].dr, snapshots[1].dr, 'two different builds must keep the same designated requirement')
  assert.notEqual(snapshots[0].hash, snapshots[1].hash, 'this must exercise different code-directory hashes')
  console.log('PASS: two different versions keep the same certificate-bound DR; wrong certificate/ad-hoc nested code rejected')
} finally { rmSync(temporary, { recursive: true, force: true }) }
