import { spawnSync } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, symlinkSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'
import { releaseVersion } from './release-version.mjs'
import { verifyMacosSigning } from './verify-macos-signing.mjs'

// Package the already signed .app; no Rust/Vite rebuild, Finder automation,
// writable-image resize or explicit mount/unmount is needed to create a DMG.
export async function packageMacosDmg(root = process.cwd(), {
  env = process.env, platform = process.platform, arch = process.arch,
  run, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
} = {}) {
  if (platform !== 'darwin') throw new Error('DMG packaging requires a native macOS runner')
  nativeBuildTarget(platform, arch, env.MICROMATRIX_BUILD_TARGET)
  const config = JSON.parse(readFileSync(path.join(root, 'apps/desktop/tauri.conf.json'), 'utf8'))
  const version = releaseVersion(root, env)
  const name = config.productName
  if (!name || /[/\\\x00-\x1f]/.test(name) || name === '.' || name === '..') throw new Error('Unsafe application productName')
  if (config.version !== version) throw new Error('Prepare the release version before creating the DMG')
  const bundle = path.join(root, 'apps/desktop/target/release/bundle')
  const application = path.join(bundle, 'macos', `${name}.app`)
  if (!existsSync(path.join(application, 'Contents/Info.plist'))) throw new Error(`Signed application is missing: ${application}`)
  const logs = path.join(root, 'apps/desktop/target/packaging-logs')
  mkdirSync(logs, { recursive: true })
  const logFile = path.join(logs, 'create-dmg.log')
  function log(message) {
    appendFileSync(logFile, `${message}\n`)
    console.log(message)
  }
  const execute = (file, args) => {
    log(`$ ${file} ${args.map(value => JSON.stringify(value)).join(' ')}`)
    if (run) return run(file, args)
    const result = spawnSync(file, args, {
      env, encoding: 'utf8', timeout: 300_000, maxBuffer: 16 * 1024 * 1024,
    })
    if (result.stdout) log(result.stdout.trimEnd())
    if (result.stderr) log(result.stderr.trimEnd())
    if (result.error || result.status !== 0) {
      const error = new Error(`${file} failed: ${result.error?.message ?? `exit ${result.status}, signal ${result.signal ?? 'none'}`}`)
      error.transient = /resource busy|temporarily unavailable|device busy/i.test(`${result.stdout}\n${result.stderr}`)
      throw error
    }
    return result.stdout.trim()
  }
  try {
    if (!run) verifyMacosSigning(application, env)
    execute('/usr/bin/codesign', ['--verify', '--deep', '--strict', application])
    const appVersion = execute('/usr/bin/plutil', ['-extract', 'CFBundleShortVersionString', 'raw', '-o', '-', path.join(application, 'Contents/Info.plist')])
    if (appVersion !== version) throw new Error(`Signed .app version ${appVersion} does not match ${version}`)
    const output = path.join(bundle, 'dmg')
    mkdirSync(output, { recursive: true })
    const temporary = mkdtempSync(path.join(output, '.dmg-stage-'))
    try {
      const source = path.join(temporary, 'contents')
      mkdirSync(source)
      const stagedApp = path.join(source, `${name}.app`)
      execute('/usr/bin/ditto', [application, stagedApp])
      symlinkSync('/Applications', path.join(source, 'Applications'))
      execute('/usr/bin/codesign', ['--verify', '--deep', '--strict', stagedApp])
      const image = path.join(temporary, 'installer.dmg')
      for (let attempt = 1; attempt <= 3; attempt++) {
        log(`DMG creation attempt ${attempt}/3`)
        try {
          execute('/usr/bin/hdiutil', [
            'create', '-verbose', '-ov', '-volname', name, '-fs', 'HFS+',
            '-srcfolder', source, '-format', 'UDZO', image,
          ])
          break
        } catch (error) {
          // Retry only known transient disk-image failures. Bad signatures,
          // missing permissions and invalid images must fail immediately.
          if (attempt === 3 || !error.transient) throw error
          rmSync(image, { force: true })
          await sleep(attempt * 2000)
        }
      }
      execute('/usr/bin/hdiutil', ['verify', '-verbose', image])
      const target = path.join(output, `${name}_${version}_${arch === 'arm64' ? 'aarch64' : 'x64'}.dmg`)
      renameSync(image, target)
      log(`PASS: verified read-only DMG ${target}; source .app unchanged`)
      return target
    } finally {
      rmSync(temporary, { recursive: true, force: true })
    }
  } catch (error) {
    log(`FAIL: ${error.message}`)
    // This is read-only diagnostics, not detaching unrelated user images.
    try { execute('/usr/bin/hdiutil', ['info']) } catch { /* retain the original failure */ }
    throw error
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await packageMacosDmg()
