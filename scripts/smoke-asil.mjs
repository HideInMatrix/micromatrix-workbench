import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { mkdtemp, mkdir, readFile, writeFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { execFileSync } from 'node:child_process'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { ComputerUseRuntime, DeclarativeAdapter, createComputerUseServer, assembleExtension, auditBundle,
  qualifyProfile, probeExtension, loadDeclarativeProviders, resolveJsonPointer, renderTemplate, renderPathTemplate } from '../packages/computer-use/dist/index.js'
import { byteSha256 } from '../packages/computer-use/dist/softwaregen/io.js'

const examples = path.resolve(import.meta.dirname, '../third_party/asil/softwaregen-examples')
const fixture = async name => JSON.parse(await readFile(path.join(examples, name), 'utf8'))
const directory = await mkdtemp(path.join(tmpdir(), 'mm-softwaregen-')), root = path.join(directory, 'workspace'), control = path.join(directory, 'approved')
const marker = randomUUID(), secret = randomUUID(), providers = [], clients = [], runtimes = [], servers = []
const worker = path.join(control, 'reference-state.mjs')
const workerText = `
import {readFile,writeFile} from 'node:fs/promises';
const [flag,file,command,id,value]=process.argv.slice(2);
if(flag!=='--state' || file!=='reference_state.json') throw new Error('Unexpected input');
const doc=JSON.parse(await readFile(file,'utf8'));
if(command==='set-value') { const matches=doc.items.filter(item=>item.id===id); if(matches.length!==1) throw new Error('Missing item'); matches[0].value=value; await writeFile(file,JSON.stringify(doc)); }
else if(command!=='observe') throw new Error('Unexpected operation');
console.log(JSON.stringify(doc));
`
const connect = async adapters => {
  const runtime = new ComputerUseRuntime(adapters, true), client = new Client({ name: 'softwaregen-regression', version: '1' })
  const server = createComputerUseServer(runtime, { permissions() { throw new Error('Regression must not request native permissions') } })
  const [ct, st] = InMemoryTransport.createLinkedPair(); await server.connect(st); await client.connect(ct)
  clients.push(client); servers.push(server); runtimes.push(runtime)
  const call = async (name, args = {}, expectedError) => {
    const result = await client.callTool({ name, arguments: args }), parsed = JSON.parse(result.content[0].text)
    if (expectedError) { assert.equal(result.isError, true); assert.equal(parsed.error, expectedError); return parsed }
    assert.notEqual(result.isError, true, JSON.stringify(parsed)); return parsed
  }
  return { runtime, client, call }
}
const action = (obs, type, target, operation, args) => ({ observation_id: obs.meta.observation_id, action_type: type, target,
  params: { operation, arguments: args }, expect_observation: true })
let http
try {
  await mkdir(root); await mkdir(control); await writeFile(worker, workerText)
  const cliOutput = path.join(control, 'cli-candidate')
  const cliReport = JSON.parse(execFileSync(process.execPath, [path.resolve(import.meta.dirname, 'asil.mjs'), 'assemble', path.join(examples, 'file_backed_profile.json'), path.join(examples, 'file_backed_plan.json'), cliOutput], { encoding: 'utf8' }))
  assert.equal(cliReport.ok, true); assert.equal(cliReport.artifact_sha256, byteSha256(await readFile(path.join(cliOutput, 'extension.json'))))
  assert.throws(() => execFileSync(process.execPath, [path.resolve(import.meta.dirname, 'asil.mjs'), 'assemble', path.join(examples, 'file_backed_profile.json'), path.join(examples, 'file_backed_plan.json'), cliOutput], { stdio: 'pipe' }))
  const permission = { filesystem_root: root, executables: { node: { path: process.execPath, prefix: [worker] } }, integrity: [{ path: worker, sha256: byteSha256(Buffer.from(workerText)) }] }
  for (const stem of ['file_backed', 'native_script']) {
    const profile = await fixture(`${stem}_profile.json`), plan = await fixture(`${stem}_plan.json`)
    assert.equal(auditBundle(assembleExtension(profile, plan).bundle).ok, true, 'unchanged official contracts parse/audit')
    assert.equal(qualifyProfile(profile).tier, 'direct_declarative')
    profile.runtime.allowed_executables = ['node']
    for (const view of plan.observation_views) {
      if (view.probe.transport === 'json_file') view.probe.path = 'reference_state.json'
      else view.probe.argv = ['node', worker, '--state', 'reference_state.json', 'observe']
    }
    plan.operations[0].request.argv = ['node', worker, '--state', 'reference_state.json', 'set-value', '${item_id}', '${value}']
    const source = { ...await fixture('reference_state.json'), marker }; await writeFile(path.join(root, 'reference_state.json'), JSON.stringify(source))
    const { bundle, report } = assembleExtension(profile, plan); assert.equal(report.ok, true); assert.equal(report.api_calls, 0)
    const bytes = Buffer.from(JSON.stringify(bundle)), bundleFile = path.join(control, `${stem}.json`), registry = path.join(control, `${stem}-registry.json`)
    await writeFile(bundleFile, bytes); await writeFile(registry, JSON.stringify({ schema_version: '1.0', extensions: [{ enabled: true, bundle: bundleFile, sha256: byteSha256(bytes), permissions: permission }] }))
    const installed = await loadDeclarativeProviders(registry, {}, [root]); providers.push(...installed)
    const { runtime, client, call } = await connect(installed)
    const tool = (await client.listTools()).tools.find(t => t.name === 'computer_act'); assert.equal(tool.annotations.readOnlyHint, false)
    const caps = await call('computer_capabilities'); assert.equal(caps.adapters[0].description.operation_targets[0].target, 'reference_workspace')
    assert.deepEqual(await call('computer_targets', { adapter: profile.software_id }), { [profile.software_id]: [{ target: profile.software_id, type: 'reviewed_software', label: profile.display_name }] })
    let obs = await call('computer_observe', { adapter: profile.software_id, target: profile.software_id })
    assert.equal(obs.interactive_elements.length, 2); assert.equal(obs.interactive_elements[0].metadata.view_id, 'items')
    assert.equal(obs.app_state.synchronized_with_gui, false)
    const mutation = action(obs, 'set_value', 'reference_workspace', 'set_item_value', { item_id: 'item-a', value: 'updated' })
    assert.equal((await call('computer_validate', mutation)).valid, true)
    await call('computer_validate', { ...mutation, params: { operation: 'set_item_value', arguments: { ...mutation.params.arguments, extra: true } } }, 'INVALID_ACTION')
    await call('computer_validate', { ...mutation, target: 'workspace:item-a' }, 'INVALID_ACTION')
    const result = await call('computer_act', { ...mutation, expect_observation: { target: 'workspace:item-a', value: { value: 'updated' } } })
    assert.equal(result.execution, 'executed'); assert.equal(result.verification.status, 'passed')
    const raw = JSON.parse(await readFile(path.join(root, 'reference_state.json'), 'utf8'))
    assert.equal(raw.marker, marker); assert.equal(raw.items[0].value, 'updated'); assert.deepEqual(raw.items[1], source.items[1])
    await call('computer_act', mutation, 'STALE_OBSERVATION')
    obs = result.observation; raw.items[0].value = 'external'; await writeFile(path.join(root, 'reference_state.json'), JSON.stringify(raw))
    await call('computer_act', action(obs, 'set_value', 'reference_workspace', 'set_item_value', { item_id: 'item-a', value: 'lost' }), 'STALE_OBSERVATION')
    assert.equal(JSON.parse(await readFile(path.join(root, 'reference_state.json'), 'utf8')).items[0].value, 'external')
    const fresh = await call('computer_observe', { adapter: profile.software_id, target: profile.software_id })
    assert.equal((await call('computer_inspect', { observation_id: fresh.meta.observation_id, query: 'Alpha' })).total_matches, 1)
    await call('computer_validate', action(fresh, 'batch', 'reference_workspace', 'set_item_value', { item_id: 'item-a', value: 'x' }), 'INVALID_ACTION')
    await assert.rejects(probeExtension(installed[0], { action: mutation }), e => e.code === 'READ_ONLY')
    const readOnly = new ComputerUseRuntime([installed[0]], false), roObs = await readOnly.observe({ adapter: profile.software_id, target: profile.software_id })
    await assert.rejects(readOnly.act(action(roObs, 'set_value', 'reference_workspace', 'set_item_value', { item_id: 'item-a', value: 'x' })), e => e.code === 'READ_ONLY')
    await writeFile(bundleFile, Buffer.concat([bytes, Buffer.from(' ')])); await assert.rejects(loadDeclarativeProviders(registry, {}, [root]), e => e.code === 'INTEGRITY_FAILED')
    await writeFile(bundleFile, bytes)
    const inWorkspace = path.join(root, 'registry.json'); await writeFile(inWorkspace, await readFile(registry))
    await assert.rejects(loadDeclarativeProviders(inWorkspace, {}, [root]), e => e.code === 'INVALID_REGISTRY')
    await writeFile(worker, `${workerText}\n// changed`)
    const changed = await runtime.observe({ adapter: profile.software_id, target: profile.software_id }).catch(e => e)
    if (stem === 'native_script') assert.equal(changed.code, 'INTEGRITY_FAILED')
    else await assert.rejects(runtime.act(action(changed, 'set_value', 'reference_workspace', 'set_item_value', { item_id: 'item-a', value: 'x' })), e => e.code === 'INTEGRITY_FAILED')
    await writeFile(worker, workerText)
  }
  for (const [name, source, error] of [
    ['timeout', 'setInterval(()=>{},1000)', 'TRANSPORT_TIMEOUT'],
    ['output', "console.log('x'.repeat(1024*1024+1))", 'OUTPUT_LIMIT'],
    ['stderr', `console.error(${JSON.stringify(secret)});process.exit(1)`, 'COMMAND_FAILED'],
    ['invalid', `console.log(${JSON.stringify(secret)})`, 'INVALID_RESPONSE'],
  ]) {
    const badWorker = path.join(control, `${name}.mjs`); await writeFile(badWorker, source)
    const profile = await fixture('native_script_profile.json'), plan = await fixture('native_script_plan.json')
    profile.runtime.allowed_executables = ['node']; profile.runtime.request_timeout_s = name === 'timeout' ? 0.2 : 2
    plan.observation_views[0].probe.argv = ['node', badWorker]
    plan.operations[0].request.argv = ['node', badWorker, '${item_id}', '${value}']
    const permissions = { filesystem_root: root, executables: { node: { path: process.execPath, prefix: [badWorker] } }, integrity: [{ path: badWorker, sha256: byteSha256(Buffer.from(source)) }] }
    const provider = await DeclarativeAdapter.create(assembleExtension(profile, plan).bundle, permissions)
    try { await assert.rejects(provider.observe(provider.id), e => e.code === error && !e.message.includes(secret)) } finally { await provider.close() }
  }
  // Ordinary Gitea-compatible routes, not /state /action or CAS receipts.
  const repositories = [{ id: 1, name: 'one', full_name: 'owner/one', description: marker, private: false }, { id: 2, name: 'two', full_name: 'owner/two', description: marker, private: false }]
  const initialRepos = structuredClone(repositories), requests = []; let id = 2
  http = createServer(async (req, res) => {
    requests.push({ method: req.method, path: req.url })
    if (req.headers.authorization !== `token ${secret}`) { res.writeHead(401).end(secret); return }
    const route = req.url.split('?')[0]
    if (route === '/redirect') { res.writeHead(302, { location: '/api/v1/user/repos' }).end(); return }
    if (route === '/hang') return
    if (route === '/bad') { res.writeHead(500).end(secret); return }
    if (route === '/large') { res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify('x'.repeat(1024 * 1024))); return }
    if (route === '/text') { res.writeHead(200, { 'content-type': 'text/plain' }).end(secret); return }
    if (route === '/api/v1/user/repos' && req.method === 'GET') { res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(repositories)); return }
    if (route === '/api/v1/user/repos' && req.method === 'POST') {
      let body = ''; for await (const chunk of req) body += chunk
      const params = JSON.parse(body); assert.equal(typeof params.private, 'boolean'); assert.equal(typeof params.auto_init, 'boolean')
      repositories.push({ id: ++id, name: params.name, full_name: `owner/${params.name}`, description: params.description, private: params.private })
      res.writeHead(201, { 'content-type': 'application/json' }).end(JSON.stringify({ deliberately_not_state: true })); return
    }
    if (route.startsWith('/api/v1/repos/owner/') && req.method === 'DELETE') {
      const name = decodeURIComponent(route.split('/').at(-1)); const index = repositories.findIndex(r => r.name === name)
      if (index >= 0) repositories.splice(index, 1); res.writeHead(204).end(); return
    }
    res.writeHead(404).end(secret)
  })
  http.listen(0, '127.0.0.1'); await once(http, 'listening'); const base = `http://127.0.0.1:${http.address().port}`
  const profile = await fixture('gitea_profile.json'), privateBindings = { environment: { SOFTWAREGEN_GITEA_URL: base, SOFTWAREGEN_GITEA_TOKEN: secret } }
  const plan = { summary: 'Map official Gitea profile repositories', observation_views: [{ id: 'repositories', description: 'Repository objects',
    probe: { transport: 'http_json', path: '/api/v1/user/repos', evidence_refs: ['ev_repo_list'] },
    element: { id_prefix: 'repo:', id_pointer: '/id', type: 'repository', label_pointer: '/full_name', value_fields: { name: '/name', description: '/description', private: '/private' }, actions: ['create_repository', 'delete_repository'], evidence_refs: ['ev_repo_list'] }, evidence_refs: ['ev_repo_list'] }],
    operations: [{ name: 'create_repository', description: 'Create isolated repository', action_type: 'api_call', target: 'gitea',
      parameters: [{ name: 'name', value_type: 'string' }, { name: 'description', value_type: 'string' }, { name: 'private', value_type: 'boolean' }, { name: 'auto_init', value_type: 'boolean' }],
      request: { transport: 'http_json', method: 'POST', path: '/api/v1/user/repos', body: { name: '${name}', description: '${description}', private: '${private}', auto_init: '${auto_init}' } }, evidence_refs: ['ev_repo_create'] },
    { name: 'delete_repository', description: 'Restore isolated repository', action_type: 'api_call', target: 'gitea', parameters: [{ name: 'owner', value_type: 'string' }, { name: 'repo', value_type: 'string' }],
      request: { transport: 'http_json', method: 'DELETE', path: '/api/v1/repos/${owner}/${repo}' }, evidence_refs: ['ev_repo_delete'] }] }
  const bundle = assembleExtension(profile, plan).bundle
  const api = await DeclarativeAdapter.create(bundle, { filesystem_root: root, base_url: base }, privateBindings); providers.push(api)
  const { call, runtime } = await connect([api])
  assert.equal(JSON.stringify(await call('computer_capabilities')).includes(secret), false)
  let obs = await call('computer_observe', { adapter: 'gitea', target: 'gitea' }); assert.equal(obs.interactive_elements.length, 2)
  const create = action(obs, 'api_call', 'gitea', 'create_repository', { name: marker, description: marker, private: true, auto_init: true })
  await call('computer_validate', { ...create, params: { operation: 'create_repository', arguments: { ...create.params.arguments, private: 'true' } } }, 'INVALID_ACTION')
  const beforeMutations = requests.filter(r => r.method !== 'GET').length
  await call('computer_validate', create); assert.equal(requests.filter(r => r.method !== 'GET').length, beforeMutations)
  obs = (await call('computer_act', create)).observation; assert.equal(obs.interactive_elements.length, 3)
  await call('computer_validate', action(obs, 'api_call', 'gitea', 'delete_repository', { owner: '..', repo: marker }), 'INVALID_ACTION')
  obs = (await call('computer_act', action(obs, 'api_call', 'gitea', 'delete_repository', { owner: 'owner', repo: marker }))).observation
  assert.equal(obs.interactive_elements.length, 2); assert.deepEqual(repositories, initialRepos); assert.equal(runtime.trace().length, 2)
  const redactBundle = structuredClone(bundle), privateField = randomUUID()
  repositories[0].description = secret; for (const repo of repositories) repo.password = privateField
  redactBundle.plan.observation_views[0].element.value_fields.renamed_field = '/password'
  redactBundle.plan.observation_views[0].element.label_pointer = '/password'
  const redactProvider = await DeclarativeAdapter.create(redactBundle, { filesystem_root: root, base_url: base }, privateBindings)
  try {
    const text = JSON.stringify(await redactProvider.observe('gitea')); assert.equal(text.includes(secret), false); assert.equal(text.includes(privateField), false); assert.ok(text.includes('[redacted]'))
  } finally { await redactProvider.close(); repositories.splice(0,repositories.length,...structuredClone(initialRepos)) }
  for (const [route, error] of [['redirect', 'HTTP_FAILED'], ['bad', 'HTTP_FAILED'], ['large', 'OUTPUT_LIMIT'], ['text', 'INVALID_RESPONSE'], ['hang', 'TRANSPORT_TIMEOUT']]) {
    const altered = structuredClone(bundle); altered.plan.observation_views[0].probe.path = `/${route}`; altered.profile.runtime.request_timeout_s = route === 'hang' ? 0.2 : 2
    const provider = await DeclarativeAdapter.create(altered, { filesystem_root: root, base_url: base }, privateBindings)
    try { await assert.rejects(provider.observe('gitea'), e => e.code === error && !e.message.includes(secret)) } finally { await provider.close() }
  }
  const hanging = structuredClone(bundle); hanging.plan.operations[0].request.path = '/hang'
  const cancelledProvider = await DeclarativeAdapter.create(hanging, { filesystem_root: root, base_url: base }, privateBindings)
  try {
    const before = await cancelledProvider.observe('gitea'), cancellation = new AbortController()
    const pending = cancelledProvider.execute('gitea', before, create, cancellation.signal); setTimeout(()=>cancellation.abort(),30)
    await assert.rejects(pending, e => e.code === 'TRANSPORT_CANCELLED')
  } finally { await cancelledProvider.close() }
  await assert.rejects(DeclarativeAdapter.create(bundle, { filesystem_root: root, base_url: base + '/other' }, privateBindings), e => e.code === 'INVALID_BINDINGS')
  for (const route of ['//other.test/x', '/%2e%2e/x', '/%252e%252e/x', '/a\\b', '/a?x=1', '/a#x']) {
    const altered = structuredClone(bundle); altered.plan.operations[0].request.path = route; assert.equal(auditBundle(altered).ok, false)
  }
  const unknown = structuredClone(bundle); unknown.plan.observation_views[0].probe.evidence_refs = ['invented']; assert.equal(auditBundle(unknown).ok, false)
  assert.equal(resolveJsonPointer({ 'a/b': { '~': [42] } }, '/a~1b/~0/0'), 42)
  assert.throws(() => resolveJsonPointer([42], '/-1')); assert.throws(() => resolveJsonPointer({}, '/a~2b'))
  assert.deepEqual(renderTemplate({ bool: '${flag}', nested: '${object}' }, { flag: true, object: { x: [42] } }), { bool: true, nested: { x: [42] } })
  assert.equal(renderTemplate('value=${value}', { value: '${literal}' }), 'value=${literal}')
  for (const value of ['..', 'x/y', 'x\\y']) assert.throws(() => renderPathTemplate('/${name}', { name: value }))
  assert.equal(renderPathTemplate('/${name}', { name: 'a b' }), '/a%20b')
  if (process.platform !== 'win32') {
    const fileBundle = assembleExtension(await fixture('file_backed_profile.json'), await fixture('file_backed_plan.json')).bundle
    fileBundle.profile.runtime.allowed_executables = []
    // Probe scope tested using service action with a file observation.
    fileBundle.plan.operations = bundle.plan.operations
    fileBundle.profile.runtime = bundle.profile.runtime
    fileBundle.plan.observation_views[0].probe.path = 'escape.json'
    fileBundle.plan.observation_views[0].element.actions = []
    fileBundle.profile.evidence.push(...bundle.profile.evidence)
    await writeFile(path.join(control, 'outside.json'), JSON.stringify({ items: [] })); await symlink(path.join(control, 'outside.json'), path.join(root, 'escape.json'))
    const escaped = await DeclarativeAdapter.create(fileBundle, { filesystem_root: root, base_url: base }, privateBindings)
    try { await assert.rejects(escaped.observe(escaped.id), e => e.code === 'OUT_OF_SCOPE') } finally { await escaped.close() }
  }
  console.log('PASS: official file/native JSON plans + ordinary REST mapping; real MCP/child processes/CLI; 2→3→2 restoration; readonly/stale/pins/types/traversal/redirect/limits/timeout/cancellation. No GUI or real Gitea/Blender claim.')
} finally {
  for (const client of clients) await client.close()
  for (const runtime of runtimes) await runtime.close()
  for (const server of servers) await server.close()
  for (const provider of providers) await provider.close()
  if (http) { http.closeAllConnections(); await new Promise(resolve => http.close(resolve)) }
  await rm(directory, { recursive: true, force: true })
}
