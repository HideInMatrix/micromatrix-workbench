import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const formats = {
  'macos-arm64': ['.dmg'],
  'macos-x64': ['.dmg'],
  'windows-x64': ['.exe', '.msi'],
  'linux-x64': ['.deb', '.AppImage'],
}

// Fail closed: only the six expected desktop installers can become public.
// Standalone services, metadata and notices stay in Actions artifacts.
export function prepareReleaseAssets(input = path.resolve('build-artifacts'), output = path.resolve('release-assets')) {
  input = path.resolve(input)
  output = path.resolve(output)
  if (input === output || input.startsWith(`${output}${path.sep}`)) throw new Error('Release output must not contain the input artifacts')
  const files = readdirSync(input, { withFileTypes: true }).filter(entry => entry.isFile()).map(entry => entry.name)
  const installers = []
  for (const [profile, extensions] of Object.entries(formats)) {
    const manifest = readFileSync(path.join(input, `SHA256SUMS-${profile}.txt`), 'utf8').split(/\r?\n/)
    for (const extension of extensions) {
      const matches = files.filter(name => name.startsWith(`${profile}-`) && name.endsWith(extension))
      if (matches.length !== 1) throw new Error(`Expected exactly one ${profile} ${extension} installer; found ${matches.length}`)
      const name = matches[0]
      const digest = createHash('sha256').update(readFileSync(path.join(input, name))).digest('hex')
      if (!manifest.includes(`${digest}  ${name}`)) throw new Error(`Installer checksum mismatch: ${name}`)
      installers.push({ name, digest })
    }
  }
  installers.sort((a, b) => a.name.localeCompare(b.name))
  rmSync(output, { recursive: true, force: true })
  mkdirSync(output, { recursive: true })
  for (const { name } of installers) copyFileSync(path.join(input, name), path.join(output, name))
  writeFileSync(path.join(output, 'SHA256SUMS.txt'), installers.map(({ name, digest }) => `${digest}  ${name}\n`).join(''))
  console.log(`Prepared ${installers.length} desktop installers and one combined checksum file; no standalone service published`)
  return output
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareReleaseAssets()
