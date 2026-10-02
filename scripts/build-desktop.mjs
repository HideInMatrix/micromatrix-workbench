import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { prepareReleaseVersion } from './release-version.mjs'

const env = { ...process.env }
const localKey = path.resolve('.local/updater/micromatrix.key')
if (!env.TAURI_SIGNING_PRIVATE_KEY && existsSync(localKey)) {
  env.TAURI_SIGNING_PRIVATE_KEY = localKey
  env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD ??= ''
}
if (!env.TAURI_SIGNING_PRIVATE_KEY) throw new Error('Signed desktop builds require TAURI_SIGNING_PRIVATE_KEY; see README update signing setup')
prepareReleaseVersion()
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
execFileSync(npm, ['run', 'build:sidecar'], { stdio: 'inherit', env, ...(process.platform === 'win32' ? { shell: true } : {}) })
execFileSync(npm, ['run', 'tauri', '--', 'build', ...process.argv.slice(2)], { stdio: 'inherit', env, ...(process.platform === 'win32' ? { shell: true } : {}) })
