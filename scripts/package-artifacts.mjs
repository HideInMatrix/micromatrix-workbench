import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'
import { releaseVersion } from './release-version.mjs'

const installerFormats = {
  darwin: [['dmg', '.dmg']],
  win32: [['nsis', '.exe'], ['msi', '.msi']],
}

export function collectInstallers(bundleRoot, platform) {
  const formats = installerFormats[platform]
  if (!formats) throw new Error(`Unsupported installer platform: ${platform}`)
  return formats.flatMap(([directory, extension]) => {
    const location = path.join(bundleRoot, directory)
    const files = existsSync(location)
      ? readdirSync(location, { withFileTypes: true }).filter(entry => entry.isFile() && entry.name.endsWith(extension)).map(entry => path.join(location, entry.name))
      : []
    if (!files.length) throw new Error(`Missing ${extension} installer in ${location}`)
    return files
  })
}

export function sha256File(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

export function packageArtifacts(root = process.cwd(), env = process.env) {
  const target = nativeBuildTarget(process.platform, process.arch, env.MICROMATRIX_BUILD_TARGET)
  const version = releaseVersion(root, env)
  const profile = `${{ darwin: 'macos', win32: 'windows' }[process.platform]}-${process.arch}`
  const extension = process.platform === 'win32' ? '.exe' : ''
  const service = path.join(root, 'src-tauri/binaries', `micromatrix-service-${target}${extension}`)
  if (!existsSync(service)) throw new Error(`Build the sidecar before packaging: ${service}`)
  const cloudflared = path.join(root, 'src-tauri/binaries', `cloudflared-${target}${extension}`)
  if (!existsSync(cloudflared)) throw new Error(`Missing bundled cloudflared: ${cloudflared}`)
  const bundleRoot = path.join(root, 'src-tauri/target/release/bundle')
  const installers = collectInstallers(bundleRoot, process.platform)
  const updaterFiles = process.platform === 'darwin'
    ? readdirSync(path.join(bundleRoot, 'macos')).filter(name => name.endsWith('.app.tar.gz')).map(name => path.join(bundleRoot, 'macos', name))
    : installers
  if (updaterFiles.length !== (process.platform === 'darwin' ? 1 : 2)) throw new Error('Missing or duplicate updater packages')
  for (const file of updaterFiles) if (!existsSync(`${file}.sig`)) throw new Error(`Missing signed updater package: ${file}.sig`)

  const nodeDirectory = path.dirname(process.execPath)
  const nodeLicense = [path.join(nodeDirectory, 'LICENSE'), path.join(nodeDirectory, '../LICENSE')].find(file => existsSync(file))
  if (!nodeLicense) throw new Error('Node distribution LICENSE is required beside the Node executable or its parent directory')
  const output = path.join(root, 'dist/artifacts')
  const serviceDirectory = path.join(root, 'dist/service-package')
  rmSync(output, { recursive: true, force: true })
  rmSync(serviceDirectory, { recursive: true, force: true })
  mkdirSync(output, { recursive: true })
  mkdirSync(serviceDirectory, { recursive: true })
  // Only these explicit distribution inputs are copied; never ship .env.local,
  // saved OAuth credentials, user workspaces or other repository state.
  copyFileSync(service, path.join(serviceDirectory, `micromatrix-service${extension}`))
  copyFileSync(cloudflared, path.join(serviceDirectory, `cloudflared${extension}`))
  if (process.platform === 'darwin') {
    const application = path.join(root, 'src-tauri/binaries/micromatrix Computer Use.app')
    if (!existsSync(path.join(application, 'Contents/MacOS/micromatrix-computer'))) throw new Error('Missing bundled Computer Use application')
    // Preserve the signed bundle in internal Actions archives too. The macOS
    // service now launches this application, not the intermediate bare helper.
    execFileSync('/usr/bin/ditto', [application, path.join(serviceDirectory, 'micromatrix Computer Use.app')], { stdio: 'inherit' })
  } else if (process.platform === 'win32') {
    const computer = path.join(root, 'src-tauri/binaries', `micromatrix-computer-${target}${extension}`)
    if (!existsSync(computer)) throw new Error('Missing bundled Computer Use native helper')
    copyFileSync(computer, path.join(serviceDirectory, `micromatrix-computer${extension}`))
  }
  copyFileSync(nodeLicense, path.join(serviceDirectory, 'NODE_LICENSE'))
  for (const [source, destination] of [
    ['README.md', 'README.md'], ['.env.example', '.env.example'],
    ['THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md'],
    ['third_party/pi/LICENSE', 'PI_LICENSE'], ['.github/release-notes.md', 'KNOWN_LIMITS.md'],
    ['third_party/cloudflared/LICENSE', 'CLOUDFLARED_LICENSE'],
  ]) copyFileSync(path.join(root, source), path.join(serviceDirectory, destination))

  const label = env.GITHUB_REF_TYPE === 'tag' ? env.GITHUB_REF_NAME : `v${version}`
  const archive = path.join(output, `micromatrix-service-${label}-${profile}.${process.platform === 'win32' ? 'zip' : 'tar.gz'}`)
  if (process.platform === 'win32') {
    execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      "$ErrorActionPreference = 'Stop'; Get-ChildItem -Force -LiteralPath $env:MM_PACKAGE_DIRECTORY | Compress-Archive -DestinationPath $env:MM_PACKAGE_ARCHIVE"], {
      env: { ...process.env, MM_PACKAGE_DIRECTORY: serviceDirectory, MM_PACKAGE_ARCHIVE: archive }, stdio: 'inherit',
    })
  } else {
    execFileSync('tar', ['-czf', archive, '-C', serviceDirectory, '.'], { stdio: 'inherit' })
  }
  for (const installer of new Set([...installers, ...updaterFiles, ...updaterFiles.map(file => `${file}.sig`)])) {
    const name = `${profile}-${path.basename(installer).replace(/\s+/g, '_')}`
    copyFileSync(installer, path.join(output, name))
  }
  copyFileSync(path.join(root, 'THIRD_PARTY_NOTICES.md'), path.join(output, `THIRD_PARTY_NOTICES-${profile}.md`))
  copyFileSync(nodeLicense, path.join(output, `NODE_LICENSE-${profile}.txt`))
  copyFileSync(path.join(root, 'third_party/pi/LICENSE'), path.join(output, `PI_LICENSE-${profile}.txt`))
  writeFileSync(path.join(output, `build-${profile}.json`), `${JSON.stringify({
    appVersion: version, tag: env.GITHUB_REF_TYPE === 'tag' ? env.GITHUB_REF_NAME : null,
    commit: env.GITHUB_SHA || execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    target, node: process.version,
    experimental: env.GITHUB_REF_TYPE !== 'tag' || version.split('+')[0].includes('-'), notarized: false,
    workflowRun: env.GITHUB_RUN_ID ?? null,
  }, null, 2)}\n`)
  const assets = readdirSync(output).sort()
  writeFileSync(path.join(output, `SHA256SUMS-${profile}.txt`), assets.map(name => `${sha256File(path.join(output, name))}  ${name}\n`).join(''))
  console.log(`Packaged ${assets.length} assets with SHA-256 checksums in ${output}`)
  return output
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) packageArtifacts()
