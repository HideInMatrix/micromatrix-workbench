import { execFileSync } from 'node:child_process'
import { mkdirSync, existsSync, statSync, copyFileSync, writeFileSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'
import { buildChannel, macSigningIdentity, macReleaseRequirement } from './build-channel.mjs'

export function prepareComputerUse(root = process.cwd()) {
  const triple = nativeBuildTarget()
  const windows = process.platform === 'win32'
  const release = buildChannel() === 'release'
  const identity = windows ? null : macSigningIdentity()
  const source = path.join(root, `packages/computer-use/native/${windows ? 'windows.cs' : 'macos.swift'}`)
  const manifest = path.join(root, 'packages/computer-use/native/windows.manifest')
  const output = path.join(root, `src-tauri/binaries/micromatrix-computer-${triple}${windows ? '.exe' : ''}`)
  mkdirSync(path.dirname(output), { recursive: true })
  const buildScript = fileURLToPath(import.meta.url)
  const inputs = windows ? [source, manifest, buildScript] : [source, buildScript]
  if (!existsSync(output) || statSync(output).mtimeMs < Math.max(...inputs.map(file => statSync(file).mtimeMs))) {
    if (windows) {
      // Compile once using the Windows .NET Framework 4.8 tools. No runtime
      // PowerShell scripts, downloaded interpreters or model-supplied source.
      const framework = path.join(process.env.SystemRoot || 'C:\\Windows', 'Microsoft.NET/Framework64/v4.0.30319')
      const compiler = path.join(framework, 'csc.exe')
      const references = ['mscorlib.dll', 'System.dll', 'System.Core.dll', 'System.Web.Extensions.dll', 'System.Drawing.dll',
        'WPF/WindowsBase.dll', 'WPF/UIAutomationClient.dll', 'WPF/UIAutomationTypes.dll'].map(file => path.join(framework, file))
      for (const file of [compiler, ...references]) if (!existsSync(file)) throw new Error(`Windows Computer Use build requires .NET Framework 4.8 compiler/WPF: ${file}`)
      execFileSync(compiler, ['/nologo', '/noconfig', '/nostdlib+', '/target:exe', '/platform:x64', '/optimize+', '/langversion:5',
        `/out:${output}`, `/win32manifest:${manifest}`, ...references.map(file => `/reference:${file}`), source], { stdio: 'inherit', windowsHide: true, timeout: 120_000 })
    } else {
      const target = `${process.arch === 'arm64' ? 'arm64' : 'x86_64'}-apple-macosx11.0`
      execFileSync('/usr/bin/xcrun', ['swiftc', '-O', '-target', target, source, '-o', output], { stdio: 'inherit', timeout: 120_000 })
      execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', output], { stdio: 'inherit' })
    }
  }
  if (!windows) {
    const application = path.join(root, 'src-tauri/binaries/micromatrix Computer Use.app')
    const contents = path.join(application, 'Contents')
    mkdirSync(path.join(contents, 'MacOS'), { recursive: true })
    mkdirSync(path.join(contents, 'Resources'), { recursive: true })
    copyFileSync(output, path.join(contents, 'MacOS/micromatrix-computer'))
    copyFileSync(path.join(root, 'src-tauri/icons/icon.icns'), path.join(contents, 'Resources/icon.icns'))
    const version = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8')).version
    writeFileSync(path.join(contents, 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>org.micromatrix.computer-use${release ? '' : '.dev'}</string>
<key>CFBundleExecutable</key><string>micromatrix-computer</string>
<key>CFBundleName</key><string>micromatrix Computer Use${release ? '' : ' Dev'}</string>
<key>CFBundleDisplayName</key><string>micromatrix Computer Use${release ? '' : ' Dev'}</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>${version}</string>
<key>CFBundleShortVersionString</key><string>${version}</string>
<key>CFBundleIconFile</key><string>icon.icns</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>LSUIElement</key><true/>
<key>NSAccessibilityUsageDescription</key><string>读取和操作经你批准的应用控件。</string>
<key>NSScreenCaptureUsageDescription</key><string>仅在明确请求视觉观察时截取目标应用窗口。</string>
</dict></plist>
`)
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
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareComputerUse()
