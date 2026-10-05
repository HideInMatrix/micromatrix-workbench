import { execFileSync } from 'node:child_process'
import { mkdirSync, existsSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { nativeBuildTarget } from './build-platform.mjs'

export function prepareComputerUse(root = process.cwd()) {
  const triple = nativeBuildTarget()
  const windows = process.platform === 'win32'
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
      const references = ['mscorlib.dll', 'System.dll', 'System.Core.dll', 'System.Web.Extensions.dll',
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
  console.log(`Prepared Computer Use native helper: ${path.relative(root,output)}`)
  return output
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareComputerUse()
