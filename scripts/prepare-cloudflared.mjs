import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'

export const cloudflaredManifest = JSON.parse(readFileSync(new URL('./cloudflared-manifest.json', import.meta.url), 'utf8'))

export function cloudflaredAsset(platform = process.platform, arch = process.arch) {
  const asset = cloudflaredManifest.assets[`${platform}-${arch}`]
  if (!asset) throw new Error(`No pinned cloudflared asset for ${platform}/${arch}`)
  return { ...asset, url: `https://github.com/cloudflare/cloudflared/releases/download/${cloudflaredManifest.version}/${asset.name}` }
}

export function verifyCloudflaredAsset(bytes, asset) {
  const actual = createHash('sha256').update(bytes).digest('hex')
  if (actual !== asset.sha256) throw new Error(`cloudflared checksum mismatch for ${asset.name}: ${actual}`)
}

export async function prepareCloudflared(root = process.cwd()) {
  const target = nativeBuildTarget()
  const asset = cloudflaredAsset()
  const cache = path.join(root, '.cache/cloudflared', cloudflaredManifest.version)
  const archive = path.join(cache, asset.name)
  mkdirSync(cache, { recursive: true })
  let bytes
  if (existsSync(archive)) {
    bytes = readFileSync(archive)
    verifyCloudflaredAsset(bytes, asset)
  } else {
    const pending = `${archive}.${process.pid}.tmp`
    try {
      // Native runners provide curl; it also honors the build machine's proxy
      // settings, unlike Node 22's default fetch. Never disable TLS checks.
      execFileSync(process.platform === 'win32' ? 'curl.exe' : 'curl', [
        '--fail', '--location', '--silent', '--show-error', '--proto', '=https', '--proto-redir', '=https',
        '--connect-timeout', '20', '--max-time', '600', '--retry', '2', '--retry-delay', '1',
        '--output', pending, asset.url,
      ], { timeout: 1_900_000, windowsHide: true, stdio: 'inherit' })
      bytes = readFileSync(pending)
      verifyCloudflaredAsset(bytes, asset)
      renameSync(pending, archive)
    } finally { rmSync(pending, { force: true }) }
  }
  const output = path.join(root, 'src-tauri/binaries', `cloudflared-${target}${process.platform === 'win32' ? '.exe' : ''}`)
  const temporary = mkdtempSync(path.join(os.tmpdir(), 'mm-cloudflared-'))
  try {
    mkdirSync(path.dirname(output), { recursive: true })
    if (asset.name.endsWith('.tgz')) {
      // Extract only the explicitly named binary after verifying the archive.
      execFileSync('tar', ['-xzf', archive, '-C', temporary, 'cloudflared'])
      copyFileSync(path.join(temporary, 'cloudflared'), output)
    } else copyFileSync(archive, output)
    chmodSync(output, 0o755)
    const version = execFileSync(output, ['--version'], { encoding: 'utf8', timeout: 10_000, windowsHide: true })
    if (!version.includes(`version ${cloudflaredManifest.version} `)) throw new Error(`Unexpected cloudflared version: ${version}`)
    console.log(`Prepared ${path.relative(root, output)}: ${version.trim()}`)
    return output
  } finally {
    rmSync(temporary, { recursive: true, force: true })
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await prepareCloudflared()
