import { spawn } from 'node:child_process'

const children = new Set()
let stopping = false

function start(args, label) {
  const child = spawn(process.execPath, args, { cwd: process.cwd(), env: process.env, stdio: 'inherit' })
  children.add(child)
  child.once('exit', code => {
    children.delete(child)
    if (!stopping && code) {
      console.error(`[desktop] ${label} exited with code ${code}`)
      void stop(code)
    }
  })
  return child
}

async function stop(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) child.kill('SIGTERM')
  await Promise.all([...children].map(child => new Promise(resolve => child.once('exit', resolve))))
  process.exit(code)
}

process.once('SIGINT', () => void stop())
process.once('SIGTERM', () => void stop())

start(['--env-file-if-exists=.env.local', '--import', 'tsx', 'apps/daemon/src/main.ts'], 'daemon')
start(['node_modules/vite/bin/vite.js', '--config', 'apps/web/vite.config.ts'], 'web')
