// Use the published package CLI and its bounded I/O, not a private local port.
import { pathToFileURL } from 'node:url'
import { daemonRequire } from './computer-use-package.mjs'
await import(pathToFileURL(daemonRequire.resolve('@ouvren/computer-use/scripts/asil.mjs')).href)
