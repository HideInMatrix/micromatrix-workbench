import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// Resolve from the workspace declaring the dependency, even if npm nests it.
const daemonRequire = createRequire(new URL('../apps/daemon/package.json', import.meta.url))
export const computerUsePackageRoot = path.dirname(daemonRequire.resolve('@ouvren/computer-use/package.json'))
export const computerUseRequire = createRequire(path.join(computerUsePackageRoot, 'package.json'))
const computerUsePackage = JSON.parse(readFileSync(path.join(computerUsePackageRoot, 'package.json'), 'utf8'))
if (computerUsePackage.name !== '@ouvren/computer-use' || computerUsePackage.version !== '0.1.1') {
  throw new Error('Unexpected Computer Use package; review native/API/resource contracts before upgrading')
}

export const computerUseTargets = ['aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-pc-windows-msvc']
export function computerUseNativeResource(target) {
  if (!computerUseTargets.includes(target)) throw new Error(`Unsupported Computer Use target: ${target}`)
  const directory = path.join(computerUsePackageRoot, 'binaries', target, 'development')
  const windows = target.endsWith('windows-msvc')
  const application = windows ? undefined : path.join(directory, 'micromatrix Computer Use.app')
  const binary = windows ? path.join(directory, `micromatrix-computer-${target}.exe`)
    : path.join(application, 'Contents/MacOS/micromatrix-computer')
  const data = readFileSync(binary)
  if (windows) {
    const pe = data.length >= 64 ? data.readUInt32LE(60) : -1
    if (data.toString('ascii', 0, 2) !== 'MZ' || pe < 64 || pe + 6 > data.length
      || data.readUInt32LE(pe) !== 0x4550 || data.readUInt16LE(pe + 4) !== 0x8664) {
      throw new Error('Computer Use package must ship a Windows x64 PE helper')
    }
  } else if (data.length < 8 || data.readUInt32LE(0) !== 0xfeedfacf
    || data.readUInt32LE(4) !== (target.startsWith('aarch64') ? 0x100000c : 0x1000007)) {
    throw new Error(`Computer Use package helper has incorrect Mach-O architecture: ${target}`)
  }
  return { binary, application }
}

// Carry the actual dependency's attribution, not stale copies of its port.
export const computerUseNoticeSources = [
  ['LICENSE', 'COMPUTER_USE_LICENSE.txt'],
  ['THIRD_PARTY_NOTICES.md', 'COMPUTER_USE_NOTICES.md'],
  ['third_party/asil/LICENSE', 'ASIL_LICENSE.txt'],
  ['third_party/asil/DATA_LICENSE', 'ASIL_DATA_LICENSE.txt'],
  ['third_party/asil/NOTICE', 'ASIL_NOTICE.txt'],
  ['third_party/automation/QUICKJS_LICENSE', 'QUICKJS_LICENSE.txt'],
  ['third_party/automation/PLAYWRIGHT_LICENSE', 'PLAYWRIGHT_LICENSE.txt'],
].map(([source, name]) => [path.join(computerUsePackageRoot, source), name])
