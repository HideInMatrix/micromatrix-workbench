import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { versionFromTag } from './release-version.mjs'
import { verifyUpdaterSignature } from './verify-updater-signature.mjs'

const formats = {
  'macos-arm64': ['.dmg', '.app.tar.gz'],
  'macos-x64': ['.dmg', '.app.tar.gz'],
  'windows-x64': ['.exe', '.msi'],
}
const updaterTargets = {
  'macos-arm64': ['darwin-aarch64', '.app.tar.gz'],
  'macos-x64': ['darwin-x86_64', '.app.tar.gz'],
  'windows-x64': ['windows-x86_64', '.exe'],
}

// Public: desktop installers, two macOS updater archives, latest.json and one
// checksum file. Private service archives/metadata/notices remain in Artifacts.
export function prepareReleaseAssets(input = path.resolve('build-artifacts'), output = path.resolve('release-assets'), options = {}) {
  input = path.resolve(input)
  output = path.resolve(output)
  if (input === output || input.startsWith(`${output}${path.sep}`)) throw new Error('Release output must not contain the input artifacts')
  const tag = options.tag ?? process.env.GITHUB_REF_NAME
  const version = versionFromTag(tag)
  const repository = options.repository ?? process.env.GITHUB_REPOSITORY ?? 'HideInMatrix/micromatrix-workbench'
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error('Invalid release repository')
  const publicKey = options.publicKey ?? JSON.parse(readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8')).plugins.updater.pubkey
  const files = readdirSync(input, { withFileTypes: true }).filter(entry => entry.isFile()).map(entry => entry.name)
  const assets = []
  const platforms = {}
  for (const [profile, extensions] of Object.entries(formats)) {
    const manifest = readFileSync(path.join(input, `SHA256SUMS-${profile}.txt`), 'utf8').split(/\r?\n/)
    const metadata = JSON.parse(readFileSync(path.join(input, `build-${profile}.json`), 'utf8'))
    if (metadata.tag !== tag || metadata.appVersion !== version) throw new Error(`Stale build metadata: ${profile}`)
    function checked(name) {
      const bytes = readFileSync(path.join(input, name))
      const digest = createHash('sha256').update(bytes).digest('hex')
      if (!manifest.includes(`${digest}  ${name}`)) throw new Error(`Installer checksum mismatch: ${name}`)
      return { name, digest, bytes }
    }
    for (const extension of extensions) {
      const matches = files.filter(name => name.startsWith(`${profile}-`) && name.endsWith(extension))
      if (matches.length !== 1) throw new Error(`Expected exactly one ${profile} ${extension} installer; found ${matches.length}`)
      const asset = checked(matches[0])
      assets.push(asset)
      const [target, updateExtension] = updaterTargets[profile]
      // Preserve the installed package type: MSI stays MSI.
      // Generic targets are fallbacks for older bundle-type detection.
      if (extension === '.app.tar.gz' || profile === 'windows-x64') {
        const signature = checked(`${asset.name}.sig`).bytes.toString('utf8').trim()
        verifyUpdaterSignature(asset.bytes, signature, publicKey, version)
        const entry = { signature, url: `https://github.com/${repository}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(asset.name)}` }
        if (extension === updateExtension) platforms[target] = entry
        const installer = { '.exe': 'nsis', '.msi': 'msi', '.app.tar.gz': 'app' }[extension]
        platforms[`${target}-${installer}`] = entry
      }
    }
  }
  const latest = `${JSON.stringify({
    version, pub_date: new Date().toISOString(),
    notes: options.notes ?? readFileSync(new URL('../.github/release-notes.md', import.meta.url), 'utf8'),
    platforms,
  }, null, 2)}\n`
  assets.push({ name: 'latest.json', digest: createHash('sha256').update(latest).digest('hex'), bytes: Buffer.from(latest) })
  assets.sort((a, b) => a.name.localeCompare(b.name))
  rmSync(output, { recursive: true, force: true })
  mkdirSync(output, { recursive: true })
  for (const { name } of assets) {
    if (name === 'latest.json') writeFileSync(path.join(output, name), latest)
    else copyFileSync(path.join(input, name), path.join(output, name))
  }
  writeFileSync(path.join(output, 'SHA256SUMS.txt'), assets.map(({ name, digest }) => `${digest}  ${name}\n`).join(''))
  console.log('Prepared four installers, two signed macOS update archives, latest.json and checksums; no standalone service published')
  return output
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareReleaseAssets()
