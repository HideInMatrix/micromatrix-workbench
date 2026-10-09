import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { run, logError } from '@tauri-apps/cli'

const root = fileURLToPath(new URL('../', import.meta.url))
// Pin both roots so CLI discovery and frontend hooks use the same layout on every OS.
process.env.TAURI_APP_PATH = path.join(root, 'apps/desktop')
process.env.TAURI_FRONTEND_PATH = root
process.chdir(root)

try {
  await run(process.argv.slice(2), 'npm run tauri')
} catch (error) {
  logError(error)
  process.exitCode = 1
}
