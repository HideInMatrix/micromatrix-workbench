import { execFileSync } from 'node:child_process'
import { chmod, mkdir, readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { build } from 'esbuild'
import { buildChannel } from './build-channel.mjs'

const root = process.cwd()
const webDist = path.join(root, 'apps/web/dist')
const output = path.join(root, 'dist/micromatrix-service.cjs')
const prebuiltWeb = process.argv.includes('--prebuilt-web')

if (prebuiltWeb) {
  let index
  try { index = await readFile(path.join(webDist, 'index.html'), 'utf8') } catch { /* validated below */ }
  if (!index?.trim()) throw new Error('--prebuilt-web requires a non-empty apps/web/dist/index.html; build or download the frontend artifact first')
  console.log('Reusing prebuilt apps/web/dist; skipping Vite build')
}

execFileSync(process.execPath, ['node_modules/typescript/bin/tsc', '-b', '--pretty', 'false'], {
  cwd: root,
  stdio: 'inherit',
})
if (!prebuiltWeb) {
  execFileSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--config', 'apps/web/vite.config.ts'], {
    cwd: root,
    stdio: 'inherit',
  })
}

const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml; charset=utf-8',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
}

async function collect(directory, prefix = '') {
  const result = {}
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name)
    const absolute = path.join(directory, entry.name)
    if (entry.isDirectory()) Object.assign(result, await collect(absolute, relative))
    else {
      const body = await readFile(absolute)
      result[`/${relative}`] = {
        contentType: contentTypes[path.extname(entry.name)] || 'application/octet-stream',
        bodyBase64: body.toString('base64'),
      }
    }
  }
  return result
}

const assets = await collect(webDist)
await mkdir(path.dirname(output), { recursive: true })
await build({
  absWorkingDir: root,
  entryPoints: ['apps/daemon/src/main.ts'],
  outfile: output,
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  sourcemap: false,
  banner: { js: '#!/usr/bin/env node\nconst __micromatrix_import_meta_url = require("node:url").pathToFileURL(__filename).href;\n// SEA has no node_modules package tree. Never walk outside the bundled executable\n// looking for Pi metadata (which can prompt for Documents access before Start).\nif (require("node:sea").isSea() && !process.env.PI_PACKAGE_DIR) process.env.PI_PACKAGE_DIR = require("node:path").dirname(process.execPath);' },
  define: { 'import.meta.url': '__micromatrix_import_meta_url', '__MICROMATRIX_RELEASE_BUILD__': String(buildChannel() === 'release') },
  plugins: [{
    name: 'embedded-web-assets',
    setup(buildApi) {
      buildApi.onResolve({ filter: /^@micromatrix\/web-assets$/ }, () => ({ path: 'embedded-web-assets', namespace: 'micromatrix' }))
      buildApi.onLoad({ filter: /.*/, namespace: 'micromatrix' }, () => ({
        loader: 'js',
        contents: `export const webAssets = ${JSON.stringify(assets)};`,
      }))
    },
  }],
})
await chmod(output, 0o755)
console.log(`Built ${path.relative(root, output)} with ${Object.keys(assets).length} embedded web assets`)
