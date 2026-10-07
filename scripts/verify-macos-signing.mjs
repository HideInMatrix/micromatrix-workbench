import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { buildChannel, macReleaseRequirement } from './build-channel.mjs'

// Check AFTER Tauri signs nested code, and again before archives are published.
// Verification only. Never fix an invalid build by re-signing it here.
export function verifyMacosSigning(application, env = process.env, run = execFileSync) {
  run('/usr/bin/codesign', ['--verify', '--deep', '--strict', application], { stdio: 'inherit' })
  if (buildChannel(env) !== 'release') return
  const identifier = JSON.parse(readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8')).identifier
  const helper = path.join(application, 'Contents/Helpers/micromatrix Computer Use.app')
  for (const [target, id] of [[application, identifier], [helper, 'org.micromatrix.computer-use']]) {
    run('/usr/bin/codesign', ['--verify', '--strict', '--test-requirement', macReleaseRequirement(env, id), target], { stdio: 'inherit' })
    const dr = run('/usr/bin/codesign', ['-d', '-r-', target], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
    // Reject a cdhash-bound DR even if the certificate test itself passes.
    if (!dr.includes('designated =>') || /\bcdhash\b/.test(dr) || !dr.toUpperCase().includes(env.APPLE_SIGNING_CERTIFICATE_SHA1.toUpperCase())) throw new Error('Release designated requirement must pin the long-lived certificate, not the current code hash')
  }
  console.log('PASS: final macOS app and Computer Use have the pinned certificate and stable designated requirements')
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  if (process.platform !== 'darwin') throw new Error('macOS signature verification requires macOS')
  const config = JSON.parse(readFileSync('src-tauri/tauri.conf.json', 'utf8'))
  verifyMacosSigning(path.resolve('src-tauri/target/release/bundle/macos', `${config.productName}.app`))
}
