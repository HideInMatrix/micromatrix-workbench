import { readFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export function validateReleaseVersion({ packageVersion, tauriVersion, cargoVersion, tag }) {
  const pattern = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:alpha|beta|rc)\.(?:0|[1-9]\d*))?$/
  if (typeof packageVersion !== 'string' || !pattern.test(packageVersion)) throw new Error('Invalid application version')
  if (packageVersion !== tauriVersion || packageVersion !== cargoVersion) {
    throw new Error('package.json, tauri.conf.json and Cargo.toml versions must match')
  }
  if (tag) {
    // A prerelease suffix labels a test build of the current application version.
    // The application itself retains its configured version; the manifest records
    // the full tag and commit. Never silently relabel a different core version.
    const match = /^v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))(?:-(?:alpha|beta|rc)\.(?:0|[1-9]\d*))?$/.exec(tag)
    if (!match || (tag !== `v${packageVersion}` && match[1] !== packageVersion)) {
      throw new Error(`Tag ${tag} must be v${packageVersion} or v${packageVersion}-alpha/beta/rc.N`)
    }
  }
  return packageVersion
}

export function releaseVersion(root = process.cwd(), env = process.env) {
  const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'))
  const tauri = JSON.parse(readFileSync(path.join(root, 'src-tauri/tauri.conf.json'), 'utf8'))
  const cargo = readFileSync(path.join(root, 'src-tauri/Cargo.toml'), 'utf8')
  const packageSection = cargo.split(/^\[package\]\s*$/m)[1]?.split(/^\[/m)[0]
  const cargoVersion = /^version\s*=\s*"([^"]+)"/m.exec(packageSection ?? '')?.[1]
  return validateReleaseVersion({
    packageVersion: pkg.version, tauriVersion: tauri.version, cargoVersion,
    tag: env.GITHUB_REF_TYPE === 'tag' ? env.GITHUB_REF_NAME : undefined,
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  console.log(`Validated application version: ${releaseVersion()}`)
}
