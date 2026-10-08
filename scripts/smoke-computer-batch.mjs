import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {randomUUID} from 'node:crypto'
import {once} from 'node:events'
import {spawn} from 'node:child_process'
import {createServer} from 'node:http'
import {Client} from '@modelcontextprotocol/sdk/client/index.js'
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js'
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js'
import {ComputerUseRuntime,ComputerScriptRunner,JsonDocumentAdapter,VisualDesktopAdapter,DesktopProxy,desktopPlatform,BrowserAdapter,createComputerUseServer} from '../packages/computer-use/dist/index.js'

for(let i=2;i<process.argv.length;i++){
  const flag=process.argv[i]
  assert.ok(['--service-entry','--service-executable','--browser-executable'].includes(flag),`Unknown smoke argument: ${flag}`)
  assert.ok(process.argv[++i]&&!process.argv[i].startsWith('--'),`${flag} requires a path`)
}
const serviceFlag=process.argv.indexOf('--service-entry'),executableFlag=process.argv.indexOf('--service-executable')
assert.ok(serviceFlag<0||executableFlag<0,'Choose CJS entry or SEA executable, not both')
assert.ok(serviceFlag<0&&executableFlag<0||['darwin','win32'].includes(process.platform),'Packaged native Computer Use requires macOS/Windows; use the direct browser batch on Linux, not an unsupported desktop MCP')
// Real QuickJS/WASM + MCP + file I/O. Native proxy doubles are explicitly not GUI tests.
const directory=await mkdtemp(path.join(tmpdir(),'mm-computer-batch-')),marker=randomUUID(),file=path.join(directory,'input.json')
const runtime=new ComputerUseRuntime([new JsonDocumentAdapter(directory)],true),runner=new ComputerScriptRunner(runtime)
const client=new Client({name:'computer-batch-regression',version:'1'}),server=createComputerUseServer(runtime,{permissions:async()=>({fixture:true})})
const [ct,st]=InMemoryTransport.createLinkedPair()
const invoke=async(c,code)=>c.callTool({name:'computer_run',arguments:{code,timeout_ms:3000}},undefined,{timeout:10_000})
const packagedTransport=(extra=[])=>new StdioClientTransport({command:executableFlag>=0?path.resolve(process.argv[executableFlag+1]):process.execPath,
  args:[...(executableFlag>=0?[]:[path.resolve(process.argv[serviceFlag+1])]),'--computer-use-mcp','--allow-actions','--workspace',directory,...extra],stderr:'pipe'})
const mutation=`const s=await computer.observe({adapter:'json',target:'input.json'});await computer.act({observation_id:s.meta.observation_id,action_type:'modify_file',target:'json:/status',params:{value:'passed'},expect_observation:{target:'json:/status',value:'passed'}});`
let child,browser,web,packagedClient
try{
  await writeFile(file,JSON.stringify({marker,status:'pending'}));await server.connect(st);await client.connect(ct)
  assert.equal((await client.listTools()).tools.length,9)
  const result=await invoke(client,`${mutation}return (await computer.observe({adapter:'json',target:'input.json'})).interactive_elements.find(n=>n.id==='json:/status').value;`)
  assert.notEqual(result.isError,true);assert.equal(JSON.parse(result.content[0].text).result,'passed');assert.deepEqual(JSON.parse(await readFile(file,'utf8')),{marker,status:'passed'})
  assert.deepEqual((await runner.run({code:'return [typeof process,typeof require,typeof fetch,typeof setTimeout,typeof WebAssembly];'})).result,['undefined','undefined','undefined','undefined','undefined'])
  assert.equal((await runner.run({code:'return computer.observe.constructor("return typeof process")();'})).result,'undefined')
  const bad=await invoke(client,'await computer.observe({adapter:"json",target:"missing.json"});'+mutation);assert.equal(bad.isError,true)
  assert.equal(JSON.parse(await readFile(file,'utf8')).status,'passed')
  await writeFile(file,JSON.stringify({marker,status:'pending'}))
  const caught=await invoke(client,'try{await computer.observe({adapter:"json",target:"missing.json"})}catch{}'+mutation);assert.equal(caught.isError,true)
  assert.equal(JSON.parse(await readFile(file,'utf8')).status,'pending','Guest catch must not resume after a host failure')
  await runner.run({code:`const s=await computer.observe({adapter:'json',target:'input.json'});computer.act({observation_id:s.meta.observation_id,action_type:'modify_file',target:'json:/status',params:{value:'passed'}});return 'queued';`})
  assert.equal(JSON.parse(await readFile(file,'utf8')).status,'passed','Unawaited host action must finish before batch success')
  await assert.rejects(runner.run({code:'while(true){}',timeout_ms:100}),e=>['SCRIPT_FAILED','SCRIPT_INTERRUPTED','SCRIPT_CANCELLED'].includes(e.code))
  await assert.rejects(runner.run({code:'return "x".repeat(100000);'}),e=>e.code==='SCRIPT_OUTPUT_LIMIT')
  await assert.rejects(runner.run({code:'const a=[];for(let i=0;i<40;i++)a.push(computer.capabilities());await Promise.all(a);'}),e=>e.code==='SCRIPT_CALL_LIMIT')
  await assert.rejects(runner.run({code:'await new Promise(()=>{});',timeout_ms:100}),e=>e.code==='SCRIPT_CANCELLED')
  const readonly=new ComputerUseRuntime([new JsonDocumentAdapter(directory)],false),roRunner=new ComputerScriptRunner(readonly)
  await assert.rejects(roRunner.run({code:mutation}),e=>e.code==='READ_ONLY');roRunner.close();await readonly.close()
  const abort=new AbortController(),waiting=runner.run({code:'await new Promise(()=>{});',timeout_ms:5000},abort.signal)
  await new Promise(resolve=>setTimeout(resolve,10));await assert.rejects(runner.run({code:'return 1;'}),e=>e.code==='BUSY');abort.abort();await assert.rejects(waiting,e=>e.code==='SCRIPT_CANCELLED')
  for(const os of ['darwin','win32']){
    const calls=[],native={revision:'native',app_state:{active:true},interactive_elements:[{id:'native:button',type:'button',label:'Native',editable:false,available_actions:['invoke_function'],children:[],metadata:{operations:['press'],secure:false}}],environment:{truncated:false},navigation:[],data_summary:'Native proxy double'}
    const packet={state:native,frame:{revision:'a'.repeat(64),width:100,height:100,bounds:{x:-300,y:20,width:200,height:200},window_id:'1',mimeType:'image/jpeg',data:Buffer.from([255,216,255,217]).toString('base64')},ocr:[{text:'Save',confidence:0.9,bounds:{x:10,y:10,width:30,height:20}}],ocr_available:true}
    const desktop=new DesktopProxy(desktopPlatform(os),'/never-spawned',{request:async(op,args)=>{calls.push([op,args]);return op==='visual_observe'?packet:{}},close:async()=>{}})
    const visual=new VisualDesktopAdapter(desktop),r=new ComputerUseRuntime([visual],true),obs=await r.observe({adapter:'desktop-visual',target:'pid:12'})
    assert.equal(obs.interactive_elements.find(n=>n.id==='ocr:0').metadata.source,'ocr');assert.equal(obs.interactive_elements[0].metadata.source,'accessibility');assert.equal(r.image(obs.meta.observation_id).mimeType,'image/jpeg')
    await assert.rejects(r.act({observation_id:obs.meta.observation_id,action_type:'invoke_function',target:'visual:surface',params:{operation:'click',x:999,y:0}}),e=>e.code==='INVALID_ACTION')
    const fresh=await r.observe({adapter:'desktop-visual',target:'pid:12'});await r.act({observation_id:fresh.meta.observation_id,action_type:'invoke_function',target:'ocr:0',params:{operation:'click'}})
    assert.deepEqual(calls.find(([op])=>op==='visual_act')[1].params,{operation:'click',x:25,y:20})
    packet.frame.data='not-base64';await assert.rejects(r.observe({adapter:'desktop-visual',target:'pid:12'}),e=>e.code==='INVALID_FRAME');await r.close()
  }
  // Explicit optional test: launch a disposable headless browser, never use the user's profile/tabs.
  const browserFlag=process.argv.indexOf('--browser-executable')
  if(browserFlag>=0){
    const executable=process.argv[browserFlag+1];assert.ok(executable&&path.isAbsolute(executable))
    web=createServer((req,res)=>{if(req.url==='/redirect'){res.writeHead(302,{location:'https://outside.invalid/'}).end();return}
      if(req.url==='/secure'){res.writeHead(200,{'content-type':'text/html'}).end('<!doctype html>'+ '<button>Fixture</button>'.repeat(305)+'<input type="password" value="SECURE_PRIVATE">');return}
      res.writeHead(200,{'content-type':'text/html'}).end('<!doctype html><title>Fixture</title><label>Name<input id="name"></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Apply</button><output role="status">pending</output><input type="hidden" id="internal" value="HIDDEN_PRIVATE"><select id="mode" aria-label="Mode"><option value="a">A</option><option value="b">B</option></select><input type="button" value="Other"><input type="checkbox" aria-label="Checked">')})
    web.listen(0,'127.0.0.1');await once(web,'listening');const origin=`http://127.0.0.1:${web.address().port}`
    const profile=path.join(directory,'browser-profile');await mkdir(profile)
    // Windows hosted runners cache Chromium under a user directory which its
    // sandbox children cannot execute. This exception is confined to our owned
    // CI fixture, like Playwright's default launch mode; never a product option.
    const fixtureArgs=process.platform==='win32'&&process.env.CI==='true'?['--no-sandbox']:[]
    if(fixtureArgs.length)console.log('CI fixture only: owned Windows Chromium runs without sandbox; sandboxed user-browser launch is not verified')
    child=spawn(executable,['--headless=new','--no-first-run','--no-default-browser-check','--disable-extensions',...fixtureArgs,'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',`--user-data-dir=${profile}`,origin],{stdio:['ignore','ignore','pipe']})
    let stderr='';child.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-8192)})
    const deadline=Date.now()+10_000;let endpoint
    while(Date.now()<deadline){endpoint=stderr.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[a-z0-9-]+)/i)?.[1];if(endpoint)break;await new Promise(resolve=>setTimeout(resolve,50))}
    assert.ok(endpoint,'Owned test browser must provide explicit loopback WebSocket')
    // A listening socket precedes renderer readiness, notably on cold Windows
    // runners. Wait for our own page to finish initialization before attaching;
    // no model action is retried and the product connection deadline is unchanged.
    const debuggerUrl=new URL(endpoint);debuggerUrl.protocol='http:';debuggerUrl.pathname='/json/list'
    const pageDeadline=Date.now()+30000;let pageReady=false
    while(Date.now()<pageDeadline){
      assert.equal(child.exitCode,null,`Owned browser exited during readiness: ${stderr}`)
      try{const pages=await fetch(debuggerUrl,{signal:AbortSignal.timeout(1000)}).then(r=>r.json());pageReady=pages.some(p=>p.type==='page'&&p.title==='Fixture'&&p.url===`${origin}/`)}catch{}
      if(pageReady)break;await new Promise(resolve=>setTimeout(resolve,100))
    }
    assert.ok(pageReady,`Owned browser never loaded the isolated fixture: ${stderr}`)
    browser=new BrowserAdapter({endpoint,allowedOrigins:[`${origin}/`]})
    let tabs=[];try{for(let i=0;i<50&&!tabs.length;i++){tabs=await browser.targets();if(!tabs.length)await new Promise(resolve=>setTimeout(resolve,50))}}catch(error){console.error(`Owned browser initialization diagnostic: ${stderr}`);throw error}assert.equal(tabs.length,1)
    const r=new ComputerUseRuntime([browser],true),js=new ComputerScriptRunner(r)
    try{const batch=await js.run({code:`const page=browser.page(${JSON.stringify(tabs[0].target)});await page.getByRole('textbox',{name:'Name'}).fill('batch-${marker}');await page.getByRole('button',{name:'Apply'}).click();return (await page.observe()).interactive_elements.find(n=>n.type==='status').label;`})
      assert.equal(batch.result,`batch-${marker}`)
      const dom=await r.observe({adapter:'browser',target:tabs[0].target});assert.equal(dom.interactive_elements.find(n=>n.metadata?.dom_id==='internal').value,null);assert.ok(!JSON.stringify(dom).includes('HIDDEN_PRIVATE'))
      assert.equal(dom.interactive_elements.find(n=>n.label==='Other').type,'button');assert.equal(dom.interactive_elements.find(n=>n.label==='Checked').editable,false)
      const selected=await js.run({code:`const p=browser.page(${JSON.stringify(tabs[0].target)});await p.getByRole('combobox',{name:'Mode'}).selectOption('b');return (await p.observe()).interactive_elements.find(n=>n.metadata?.dom_id==='mode').value;`});assert.equal(selected.result,'b')
      const image=await r.observe({adapter:'browser',target:tabs[0].visual_target});assert.equal(r.image(image.meta.observation_id).mimeType,'image/jpeg')
      const images=await js.run({code:`for(let i=0;i<4;i++)await browser.page(${JSON.stringify(tabs[0].target)}).observe(true);return 'captured';`});
      assert.equal(images.images.length,3);assert.deepEqual(images.image_observations.map(n=>n.step),[2,3,4]);assert.equal(images.image_observations[0].adapter,'browser')
      if(serviceFlag>=0||executableFlag>=0){
        const c=new Client({name:'bundled-playwright-resources',version:'1'}),transport=packagedTransport(['--browser-configuration',JSON.stringify({endpoint,allowedOrigins:[`${origin}/`]})])
        try{await c.connect(transport);const p=await invoke(c,`const tabs=await browser.tabs();const page=browser.page(tabs.browser[0].target);await page.getByRole('textbox',{name:'Name'}).fill('bundled-${marker}');await page.getByRole('button',{name:'Apply'}).click();await page.observe(true);return (await page.observe()).interactive_elements.find(n=>n.type==='status').label;`)
          assert.notEqual(p.isError,true,JSON.stringify(p.content));assert.equal(JSON.parse(p.content[0].text).result,`bundled-${marker}`);assert.equal(p.content[1].type,'image')
          console.log('PASS: bundled service loads packaged Playwright static resources and embedded WASM; real browser batch image/readback')
        }finally{await c.close();await transport.close()}
      }
      const boundary=await r.observe({adapter:'browser',target:tabs[0].target})
      await assert.rejects(r.act({observation_id:boundary.meta.observation_id,action_type:'navigate',target:'browser:page',params:{url:'https://outside.invalid/'}}),e=>e.code==='OUT_OF_SCOPE')
      await js.run({code:`await browser.page(${JSON.stringify(tabs[0].target)}).goto(${JSON.stringify(origin+'/secure')});`})
      const secure=await r.observe({adapter:'browser',target:tabs[0].target});assert.equal(secure.environment.aria_snapshot,'[omitted: secure fields]');assert.equal(secure.environment.truncated,true)
      await assert.rejects(r.observe({adapter:'browser',target:tabs[0].visual_target}),e=>e.code==='VISUAL_SECURE_CONTENT')
      await assert.rejects(js.run({code:`await browser.page(${JSON.stringify(tabs[0].target)}).goto(${JSON.stringify(origin+'/redirect')});`}),e=>['SCRIPT_HOST_FAILED','OUT_OF_SCOPE'].includes(e.code))
      console.log('PASS: real owned headless Chromium + Playwright DOM/ARIA/image + QuickJS fill/click/readback; cross-origin redirect refused')
    }finally{js.close();await r.close();browser=undefined}
    assert.equal(child.exitCode,null,'Disconnect must not close the attached browser process')
  }
  if(serviceFlag>=0||executableFlag>=0){
    packagedClient=new Client({name:'packaged-batch-regression',version:'1'})
    const transport=packagedTransport()
    await packagedClient.connect(transport);const p=await invoke(packagedClient,'return [typeof process,(await computer.capabilities()).protocol];');assert.notEqual(p.isError,true);assert.deepEqual(JSON.parse(p.content[0].text).result,['undefined','micromatrix-asil/1'])
    await packagedClient.close();packagedClient=undefined;await transport.close();console.log('PASS: bundled service loads embedded QuickJS WASM without external engine assets')
  }
  console.log('PASS: real QuickJS/MCP batch mutation+readback, isolated globals, stop-on-error, readonly, CPU/output/call/time limits and cancellation; native macOS/Windows routing doubles only, no real desktop input')
}finally{
  runner.close();await client.close();await server.close();await runtime.close();await packagedClient?.close();await browser?.close();if(child&&child.exitCode===null){child.kill('SIGTERM');await Promise.race([once(child,'exit'),new Promise(resolve=>setTimeout(resolve,1500))]);if(child.exitCode===null)child.kill('SIGKILL')}
  if(web){web.closeAllConnections();await new Promise(resolve=>web.close(resolve))}await rm(directory,{recursive:true,force:true})
}
