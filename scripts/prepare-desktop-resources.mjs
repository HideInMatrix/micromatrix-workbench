import { copyFileSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export function prepareDesktopResources(root = process.cwd()) {
  const nodeDirectory = path.dirname(process.execPath)
  const nodeLicense = [path.join(nodeDirectory, 'LICENSE'), path.join(nodeDirectory, '../LICENSE')].find(file => existsSync(file))
  if (!nodeLicense) throw new Error('Node distribution LICENSE is required for desktop packaging')
  const sources = [
    [nodeLicense, 'NODE_LICENSE.txt'],
    [path.join(root, 'third_party/pi/LICENSE'), 'PI_LICENSE.txt'],
    [path.join(root, 'THIRD_PARTY_NOTICES.md'), 'THIRD_PARTY_NOTICES.md'],
    [path.join(root, '.github/release-notes.md'), 'KNOWN_LIMITS.md'],
  ]
  for (const [source] of sources) {
    if (!existsSync(source)) throw new Error(`Missing desktop notice: ${source}`)
  }
  const output = path.join(root, 'src-tauri/resources/notices')
  rmSync(output, { recursive: true, force: true })
  mkdirSync(output, { recursive: true })
  for (const [source, name] of sources) copyFileSync(source, path.join(output, name))
  return output
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) prepareDesktopResources()
