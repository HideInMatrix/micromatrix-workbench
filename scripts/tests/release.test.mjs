import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { nativeBuildTarget } from '../build-platform.mjs'
import { validateReleaseVersion, releaseVersion } from '../check-release-version.mjs'
import { collectInstallers, packageArtifacts, sha256File } from '../package-artifacts.mjs'

test('native target resolution rejects unsupported CPUs and cross-architecture sidecars', () => {
  assert.equal(nativeBuildTarget('darwin', 'arm64', ''), 'aarch64-apple-darwin')
  assert.equal(nativeBuildTarget('darwin', 'x64', ''), 'x86_64-apple-darwin')
  assert.equal(nativeBuildTarget('win32', 'x64', ''), 'x86_64-pc-windows-msvc')
  assert.equal(nativeBuildTarget('linux', 'x64', ''), 'x86_64-unknown-linux-gnu')
  assert.throws(() => nativeBuildTarget('linux', 'ia32', ''), /Unsupported/)
  assert.throws(() => nativeBuildTarget('darwin', 'arm64', 'x86_64-apple-darwin'), /not requested/)
})

test('release version validation requires consistent versions and rejects unrelated tags', () => {
  const versions = { packageVersion: '0.1.0', tauriVersion: '0.1.0', cargoVersion: '0.1.0' }
  assert.equal(validateReleaseVersion(versions), '0.1.0')
  for (const tag of ['v0.1.0', 'v0.1.0-alpha.1', 'v0.1.0-beta.0', 'v0.1.0-rc.2']) {
    assert.equal(validateReleaseVersion({ ...versions, tag }), '0.1.0')
  }
  for (const tag of ['v9.0.0', 'v0.1.0-../../escape', 'v0.1.0-alpha.01', '0.1.0', 'v0.1.0garbage']) {
    assert.throws(() => validateReleaseVersion({ ...versions, tag }), /Tag/)
  }
  assert.throws(() => validateReleaseVersion({ ...versions, cargoVersion: '0.2.0' }), /must match/)
  assert.throws(() => validateReleaseVersion({}), /Invalid/)
  assert.equal(releaseVersion(path.resolve(import.meta.dirname, '../..'), {}), '0.1.0')
})

test('installer discovery requires every expected format and ignores unrelated outputs', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'mm-installer-test-'))
  try {
    mkdirSync(path.join(directory, 'msi'))
    writeFileSync(path.join(directory, 'msi', 'example.msi'), 'fixture')
    assert.throws(() => collectInstallers(directory, 'win32'), /Missing .exe/)
    mkdirSync(path.join(directory, 'nsis'))
    writeFileSync(path.join(directory, 'nsis', 'setup.exe'), 'fixture')
    writeFileSync(path.join(directory, 'nsis', 'unrelated.log'), 'not an installer')
    assert.equal(collectInstallers(directory, 'win32').length, 2)
    assert.throws(() => collectInstallers(directory, 'freebsd'), /Unsupported/)
    assert.equal(sha256File(path.join(directory, 'msi', 'example.msi')), 'f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d')
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test('artifact packaging records checksums and commit, and does not ship private environment files', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'mm-package-test-'))
  function file(name, content) {
    const destination = path.join(directory, name)
    mkdirSync(path.dirname(destination), { recursive: true })
    writeFileSync(destination, content, { mode: 0o755 })
  }
  const formats = { darwin: [['dmg', 'test.dmg']], win32: [['nsis', 'setup.exe'], ['msi', 'test.msi']], linux: [['deb', 'test.deb'], ['appimage', 'test.AppImage']] }
  try {
    file('package.json', JSON.stringify({ version: '0.1.0' }))
    file('src-tauri/tauri.conf.json', JSON.stringify({ version: '0.1.0' }))
    file('src-tauri/Cargo.toml', '[package]\nname = "fixture"\nversion = "0.1.0"\n')
    file(`src-tauri/binaries/micromatrix-service-${nativeBuildTarget()}${process.platform === 'win32' ? '.exe' : ''}`, 'fake executable, never run')
    for (const [folder, name] of formats[process.platform]) file(`src-tauri/target/release/bundle/${folder}/${name}`, 'fake installer, never run')
    for (const name of ['README.md', '.env.example', 'THIRD_PARTY_NOTICES.md', 'third_party/pi/LICENSE', '.github/release-notes.md']) file(name, 'distribution fixture')
    file('.env.local', 'NEVER_SHIP_THIS_SECRET')
    file('dist/artifacts/stale-output.txt', 'must be removed')
    const output = packageArtifacts(directory, { GITHUB_SHA: 'test-commit', GITHUB_REF_TYPE: 'tag', GITHUB_REF_NAME: 'v0.1.0-alpha.1' })
    const profile = `${{ darwin: 'macos', win32: 'windows', linux: 'linux' }[process.platform]}-${process.arch}`
    const metadata = JSON.parse(readFileSync(path.join(output, `build-${profile}.json`), 'utf8'))
    assert.equal(metadata.commit, 'test-commit')
    assert.equal(metadata.tag, 'v0.1.0-alpha.1')
    const sums = readFileSync(path.join(output, `SHA256SUMS-${profile}.txt`), 'utf8').trim().split('\n')
    for (const line of sums) {
      const [expected, name] = line.split('  ')
      assert.equal(sha256File(path.join(output, name)), expected)
    }
    assert.ok(!sums.some(line => line.includes('stale-output')))
    if (process.platform !== 'win32') {
      const archive = path.join(output, `micromatrix-service-v0.1.0-alpha.1-${profile}.tar.gz`)
      const contents = execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' })
      assert.ok(contents.includes('./.env.example'))
      assert.ok(contents.includes('./NODE_LICENSE'))
      assert.ok(!contents.includes('.env.local'))
      const extracted = path.join(directory, 'extracted')
      mkdirSync(extracted)
      execFileSync('tar', ['-xzf', archive, '-C', extracted])
      assert.ok(statSync(path.join(extracted, 'micromatrix-service')).mode & 0o111, 'Unix service must remain executable after extraction')
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
