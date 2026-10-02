import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const identifier = '(?:0|[1-9]\\d*|\\d*[A-Za-z-][0-9A-Za-z-]*)'
const semver = new RegExp(`^(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)(?:-${identifier}(?:\\.${identifier})*)?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$`)

export function versionFromTag(tag) {
  const version = typeof tag === 'string' && tag.startsWith('v') ? tag.slice(1) : ''
  if (!semver.test(version)) throw new Error(`Invalid release tag ${String(tag)}; use v<major>.<minor>.<patch>, optionally with a SemVer prerelease suffix`)
  return version
}

export function releaseVersion(root = process.cwd(), env = process.env) {
  if (env.GITHUB_REF_TYPE === 'tag') return versionFromTag(env.GITHUB_REF_NAME)
  // Use the newest reachable version tag for local builds, never a tag from
  // an unrelated branch. Archive checkouts without Git keep package.json.
  if (!env.GITHUB_ACTIONS) {
    let tags = ''
    try { tags = execFileSync('git', ['tag', '--merged', 'HEAD', '--sort=-version:refname', '--list', 'v*'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }) } catch { /* Source archive */ }
    for (const tag of tags.trim().split(/\r?\n/)) {
      try { return versionFromTag(tag) } catch { /* Ignore non-release tags */ }
    }
  }
  const version = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version
  if (!semver.test(version)) throw new Error('package.json must contain a SemVer application version')
  return version
}

function cargoVersion(contents, version) {
  let inPackage = false
  let changed = false
  const lines = contents.split('\n').map(line => {
    if (line.startsWith('[')) inPackage = line.trim() === '[package]'
    if (inPackage && /^version\s*=/.test(line)) {
      changed = true
      return line.replace(/"[^"]+"/, `"${version}"`)
    }
    return line
  })
  if (!changed) throw new Error('Cargo.toml is missing [package].version')
  return lines.join('\n')
}

export function prepareReleaseVersion(root = process.cwd(), env = process.env) {
  const version = releaseVersion(root, env)
  const read = file => readFileSync(path.join(root, file), 'utf8')
  const pkg = JSON.parse(read('package.json'))
  const lock = JSON.parse(read('package-lock.json'))
  const tauri = JSON.parse(read('src-tauri/tauri.conf.json'))
  pkg.version = lock.version = lock.packages[''].version = tauri.version = version
  const cargo = cargoVersion(read('src-tauri/Cargo.toml'), version)
  const cargoLock = read('src-tauri/Cargo.lock')
  const packageVersion = /(\[\[package\]\]\r?\nname = "micromatrix-pi-mcp"\r?\nversion = )"[^"]+"/
  if (!packageVersion.test(cargoLock)) throw new Error('Cargo.lock is missing the desktop application package')
  // Resolve all inputs first. CI changes only its checkout; no git commit/tag is
  // created and internal workspace/dependency versions remain untouched.
  const updates = [
    ['package.json', `${JSON.stringify(pkg, null, 2)}\n`],
    ['package-lock.json', `${JSON.stringify(lock, null, 2)}\n`],
    ['src-tauri/tauri.conf.json', `${JSON.stringify(tauri, null, 2)}\n`],
    ['src-tauri/Cargo.toml', cargo],
    ['src-tauri/Cargo.lock', cargoLock.replace(packageVersion, `$1"${version}"`)],
    ['apps/daemon/src/version.ts', `// Release builds overwrite this value from the Git tag before compiling.\nexport const APP_VERSION = "${version}";\n`],
  ]
  for (const [file, contents] of updates) writeFileSync(path.join(root, file), contents)
  console.log(`Prepared application version ${version} from ${env.GITHUB_REF_TYPE === 'tag' ? env.GITHUB_REF_NAME : 'reachable Git tag / package.json'}`)
  return version
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareReleaseVersion()
