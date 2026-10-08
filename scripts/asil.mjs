import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { assembleExtension, auditBundle, loadDeclarativeProviders, probeExtension } from '../packages/computer-use/dist/index.js'
import { readBoundedFile, decodeJson, byteSha256 } from '../packages/computer-use/dist/softwaregen/io.js'

// Local operator CLI; not an AI-install tool. Assembly never executes a candidate.
const [command, ...args] = process.argv.slice(2)
try {
  if (command === 'assemble' && args.length === 3) {
    const [profile, plan, directory] = args
    const result = assembleExtension(decodeJson(await readBoundedFile(profile)), decodeJson(await readBoundedFile(plan)))
    const output = path.resolve(directory)
    await mkdir(path.dirname(output), { recursive: true })
    await mkdir(output, { mode: 0o700 }) // Never overwrite an existing directory/artifact.
    const bundle = `${JSON.stringify(result.bundle, null, 2)}\n`
    for (const [name, text] of [['extension.json', bundle], ['action_schema.json', `${JSON.stringify(result.actionSchema, null, 2)}\n`],
      ['generation_report.json', `${JSON.stringify(result.report, null, 2)}\n`]]) await writeFile(path.join(output, name), text, { flag: 'wx', mode: 0o600 })
    console.log(JSON.stringify({ ...result.report, bundle_file: path.join(output, 'extension.json'), artifact_sha256: byteSha256(Buffer.from(bundle)) }, null, 2))
    if (!result.report.ok) process.exitCode = 2
  } else if (command === 'audit' && args.length === 1) {
    const report = auditBundle(decodeJson(await readBoundedFile(args[0])))
    console.log(JSON.stringify(report, null, 2)); if (!report.ok) process.exitCode = 2
  } else if (command === 'probe' && args.length === 2) {
    const providers = await loadDeclarativeProviders(path.resolve(args[0]))
    try {
      const provider = providers.find(p => p.id === args[1]); if (!provider) throw new Error('Requested extension not enabled in registry')
      console.log(JSON.stringify(await probeExtension(provider), null, 2))
    } finally { await Promise.all(providers.map(p => p.close())) }
  } else throw new Error('Usage: asil assemble PROFILE PLAN NEW_DIRECTORY | audit BUNDLE | probe REGISTRY SOFTWARE_ID (read-only)')
} catch (error) {
  // Do not print parsed JSON/Zod errors or transport response bodies containing secrets.
  console.error(JSON.stringify({ ok: false, error: error?.code ?? 'LOCAL_OPERATION_FAILED', message: 'Local ASIL operation failed; check arguments, schema, pinned artifact and approved bindings' }))
  process.exitCode = 1
}
