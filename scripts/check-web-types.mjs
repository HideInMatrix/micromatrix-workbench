import {createRequire} from 'node:module'
const require=createRequire(import.meta.url)
// Product code/build stays on TS 7. Vue's official checker currently embeds
// the legacy compiler API; isolate that compatibility dependency to SFC checks.
require('vue-tsc').run(require.resolve('typescript-sfc/lib/tsc.js'))
