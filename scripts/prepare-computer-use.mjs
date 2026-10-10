import { execFileSync } from 'node:child_process'
import { mkdirSync, chmodSync, copyFileSync, cpSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { computerUsePackageRoot, computerUseNativeResource } from './computer-use-package.mjs'
import { nativeBuildTarget } from './build-platform.mjs'
import { buildChannel, macSigningIdentity, macReleaseRequirement } from './build-channel.mjs'

export function prepareComputerUse(root = process.cwd()) {
  const triple = nativeBuildTarget()
  const windows = process.platform === 'win32'
  const release = buildChannel() === 'release'
  const identity = windows ? null : macSigningIdentity()
  // npm ships all three helpers. No Swift/C# compiler, source fallback or
  // install-time script runs in workbench; missing artifacts fail the build.
  const resource = computerUseNativeResource(triple)
  const output = path.join(root, `apps/desktop/binaries/micromatrix-computer-${triple}${windows ? '.exe' : ''}`)
  mkdirSync(path.dirname(output), { recursive: true })
  if (!windows) execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', resource.application], { stdio: 'inherit' })
  copyFileSync(resource.binary, output)
  chmodSync(output, 0o755)
  if (!windows) {
    const application = path.join(root, 'apps/desktop/binaries/micromatrix Computer Use.app')
    rmSync(application, { recursive: true, force: true })
    cpSync(resource.application, application, { recursive: true })
    const contents = path.join(application, 'Contents')
    mkdirSync(path.join(contents, 'MacOS'), { recursive: true })
    mkdirSync(path.join(contents, 'Resources'), { recursive: true })
    copyFileSync(output, path.join(contents, 'MacOS/micromatrix-computer'))
    copyFileSync(path.join(root, 'apps/desktop/icons/icon.icns'), path.join(contents, 'Resources/icon.icns'))
    const version = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version
    const plist = readFileSync(path.join(computerUsePackageRoot, 'assets/macos/Info.plist'), 'utf8')
      .replaceAll('{{BUNDLE_ID}}', `org.micromatrix.computer-use${release ? '' : '.dev'}`)
      .replaceAll('{{DISPLAY_NAME}}', `micromatrix Computer Use${release ? '' : ' Dev'}`)
      .replaceAll('{{VERSION}}', version)
    writeFileSync(path.join(contents, 'Info.plist'), plist)
    // A cryptographic certificate pin + identifier, never identifier alone.
    // Self-signed builds do not require Apple's online timestamp service.
    execFileSync('/usr/bin/codesign', ['--force', '--sign', identity,
      ...(identity === '-' ? [] : ['--options', 'runtime', '--timestamp=none']),
      ...(release ? ['--requirements', `=designated => ${macReleaseRequirement().slice(1)}`] : []), application], { stdio: 'inherit' })
    execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', application], { stdio: 'inherit' })
    if (release) execFileSync('/usr/bin/codesign', ['--verify', '--strict', '--test-requirement', macReleaseRequirement(), application], { stdio: 'inherit' })
    console.log(`Prepared Computer Use application: ${path.relative(root, application)}`)
  }
  console.log(`Prepared Computer Use native helper: ${path.relative(root,output)}`)
  return output
}
