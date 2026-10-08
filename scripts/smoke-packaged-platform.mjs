import {execFileSync} from 'node:child_process'
import {existsSync} from 'node:fs'
import path from 'node:path'
import {chromium} from 'playwright-core'
import {nativeBuildTarget} from './build-platform.mjs'

// Same non-mocked browser/QuickJS/SEA acceptance on every native runner. The
// owned native GUI is separate: headless runners explicitly report unverified.
if(process.argv.length>2)throw Error('Platform acceptance takes no arguments')
const service=path.resolve('src-tauri/binaries',`micromatrix-service-${nativeBuildTarget()}${process.platform==='win32'?'.exe':''}`),browser=chromium.executablePath()
if(!existsSync(service)||!existsSync(browser))throw Error('Build SEA and explicitly install the isolated CI Chromium before platform acceptance')
for(const args of [
 ['scripts/smoke-priority.mjs'],
 ['scripts/smoke-computer-batch.mjs','--service-executable',service,'--browser-executable',browser],
 ['scripts/smoke-native-desktop.mjs','--run','--service-executable',service],
])execFileSync(process.execPath,args,{stdio:'inherit',timeout:120000})
