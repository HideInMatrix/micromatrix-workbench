import { createRequire } from 'node:module'
import { cpSync, mkdirSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// Playwright includes reviewed static JS/assets, NOT a browser or user profile.
// Lazy-load from installed resources because the Node SEA has no node_modules.
export function prepareAutomationResources(root=process.cwd()) {
  const require=createRequire(import.meta.url)
  const source=path.dirname(require.resolve('playwright-core/package.json'))
  const manifest=JSON.parse(readFileSync(path.join(source,'package.json'),'utf8'))
  if(manifest.version!=='1.63.0') throw Error('Unexpected Playwright runtime version; review resource binding before packaging')
  const destination=path.join(root,'src-tauri/resources/automation/playwright-core')
  rmSync(destination,{recursive:true,force:true});mkdirSync(path.dirname(destination),{recursive:true})
  cpSync(source,destination,{recursive:true,dereference:true})
  return destination
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)prepareAutomationResources()
