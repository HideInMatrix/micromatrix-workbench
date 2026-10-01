import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { nativeBuildTarget } from './build-platform.mjs'
import { prepareDesktopResources } from './prepare-desktop-resources.mjs'

const root = process.cwd()
const triple = nativeBuildTarget()
const serviceArgs = ['scripts/build-service.mjs']
if (process.argv.includes('--prebuilt-web')) serviceArgs.push('--prebuilt-web')
execFileSync(process.execPath, serviceArgs, { cwd: root, stdio: 'inherit' })

const extension = process.platform === 'win32' ? '.exe' : ''
const outputDir = path.join(root, 'src-tauri/binaries')
const target = path.join(outputDir, `micromatrix-service-${triple}${extension}`)
const blob = path.join(root, 'dist/micromatrix-service.blob')
const config = path.join(root, 'dist/sea-config.json')
mkdirSync(outputDir, { recursive: true })
writeFileSync(config, JSON.stringify({
  main: path.join(root, 'dist/micromatrix-service.cjs'),
  output: blob,
  disableExperimentalSEAWarning: true,
  useCodeCache: false,
  useSnapshot: false,
}))
execFileSync(process.execPath, ['--experimental-sea-config', config], { stdio: 'inherit' })
copyFileSync(process.execPath, target)
if (process.platform === 'darwin') execFileSync('codesign', ['--remove-signature', target], { stdio: 'inherit' })
const postject = path.join(root, 'node_modules/postject/dist/cli.js')
if (!existsSync(postject)) throw new Error('postject CLI is not installed')
const args = [postject, target, 'NODE_SEA_BLOB', blob, '--sentinel-fuse', 'NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2']
if (process.platform === 'darwin') args.push('--macho-segment-name', 'NODE_SEA')
execFileSync(process.execPath, args, { stdio: 'inherit' })
if (process.platform === 'darwin') execFileSync('codesign', ['--sign', '-', target], { stdio: 'inherit' })
prepareDesktopResources(root)
console.log(`Built Tauri sidecar ${path.relative(root, target)}`)
