import assert from 'node:assert/strict'
import {mkdtemp,rm,readFile,stat} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {createHash} from 'node:crypto'
import {request as httpRequest} from 'node:http'
import {createServer as reservePort} from 'node:net'
import {LocalOAuthServer} from '@micromatrix/oauth'
import {CimdClientResolver} from '../packages/oauth/dist/cimd.js'
import {McpHttpService} from '@micromatrix/mcp-server'
import {PluginRegistry} from '@micromatrix/plugin-kit'
import {probePublicService,waitForPublicService,NetworkHealthMonitor,ManagedProcess,TailscaleNetworkProvider,ExternalNetworkProvider} from '@micromatrix/network'
import {RuntimeSupervisor} from '../apps/daemon/dist/runtime.js'
import {loadConfig} from '../apps/daemon/dist/config.js'
import {createUpdateController,emptyUpdateState} from '../apps/web/dist-types/api/updateController.js'

const directory=await mkdtemp(path.join(tmpdir(),'mm-priority-')),logger={log(){}},cleanups=[]
const savedResolve=CimdClientResolver.prototype.resolve
// Isolate this fixture's public document; network origin/Host/HTTP/PKCE remain
// real. Real CIMD DNS/TLS validation is covered by its separate regression.
const clientId='https://fixture.example/oauth/client.json',redirect='https://fixture.example/callback'
CimdClientResolver.prototype.resolve=async id=>{assert.equal(id,clientId);return {client_id:clientId,redirect_uris:[redirect],token_endpoint_auth_method:'none'}}
async function service(limits={},ttl=3600){
  const registry=new PluginRegistry({workspace:directory,logger}),oauth=new LocalOAuthServer({password:'fixture-only-password',limits,accessTokenTtlSeconds:ttl,refreshTokenTtlSeconds:3600})
  const server=new McpHttpService({host:'127.0.0.1',port:0,authorization:oauth,registry,logger});await server.start()
  cleanups.push(async()=>{await server.stop();await registry.dispose()})
  return {server,oauth,base:server.localBaseUrl}
}
const verifier='a'.repeat(50),challenge=createHash('sha256').update(verifier).digest('base64url')
function params(extra={}){return new URLSearchParams({client_id:clientId,redirect_uri:redirect,response_type:'code',code_challenge_method:'S256',code_challenge:challenge,password:'fixture-only-password',...extra})}
async function post(base,endpoint,values,headers={}){return fetch(base+endpoint,{method:'POST',redirect:'manual',headers:{'content-type':'application/x-www-form-urlencoded',...headers},body:values})}
async function status(base,headers){return new Promise((resolve,reject)=>{const req=httpRequest(base+'/healthz',{headers},res=>{res.resume();res.once('end',()=>resolve(res.statusCode))});req.on('error',reject);req.end()})}
async function code(base){const response=await post(base,'/authorize',params());assert.equal(response.status,302);return new URL(response.headers.get('location')).searchParams.get('code')}
async function exchange(base,value,extra={}){return post(base,'/token',new URLSearchParams({grant_type:'authorization_code',client_id:clientId,redirect_uri:redirect,code:value,code_verifier:verifier,...extra}))}
try {
  const fixed=await service();fixed.server.setPublicBaseUrl('https://owned.example')
  const metadata=await fetch(fixed.base+'/.well-known/oauth-authorization-server',{headers:{'x-forwarded-host':'attacker.example','x-forwarded-proto':'http'}}).then(r=>r.json())
  assert.equal(metadata.issuer,'https://owned.example');assert.equal(metadata.token_endpoint,'https://owned.example/token')
  assert.equal((await fetch(fixed.base+'/mcp')).headers.get('www-authenticate'),'Bearer resource_metadata="https://owned.example/.well-known/oauth-protected-resource/mcp", scope="mcp"')
  for(const headers of [{host:'attacker.example'},{origin:'https://attacker.example'},{origin:'null'}])assert.equal(await status(fixed.base,headers),403)
  assert.equal(await status(fixed.base,{host:'owned.example',origin:'https://owned.example'}),200)
  assert.equal((await post(fixed.base,'/authorize',params({resource:'https://attacker.example/mcp'}))).status,400)
  const issuerCode=await post(fixed.base,'/authorize',params({resource:'https://owned.example/mcp'}));assert.equal(issuerCode.status,302);assert.equal(new URL(issuerCode.headers.get('location')).searchParams.get('iss'),'https://owned.example')
  console.log('PASS: fixed public OAuth issuer/resource, spoofed forwarding ignored; malicious Host/Origin rejected before authorization')

  const limited=await service({loginAttemptsPerMinute:1})
  assert.equal((await post(limited.base,'/authorize',params({password:'wrong'}))).status,302)
  const blocked=await post(limited.base,'/authorize',params(),{'x-forwarded-for':'192.0.2.10'})
  assert.equal(blocked.status,429);assert.ok(Number(blocked.headers.get('retry-after'))>0)
  const quota=await service({requestsPerMinute:2})
  for(let i=0;i<2;i++)assert.equal((await fetch(quota.base+'/.well-known/oauth-authorization-server')).status,200)
  assert.equal((await fetch(quota.base+'/.well-known/oauth-authorization-server')).status,429)
  assert.equal((await fetch(quota.base+'/healthz')).status,200)
  console.log('PASS: bounded global login/endpoint quotas with Retry-After; forged proxy IP cannot bypass; health remains available')

  const bounded=await service({maxStateEntries:2},1)
  const first=await code(bounded.base),second=await code(bounded.base)
  assert.equal((await post(bounded.base,'/authorize',params())).status,503)
  const one=await exchange(bounded.base,first);assert.equal(one.status,200);const issued=await one.json()
  const two=await exchange(bounded.base,second);assert.equal(two.status,200);const secondIssued=await two.json()
  const third=await code(bounded.base)
  assert.equal((await exchange(bounded.base,third)).status,503)
  const refresh=new URLSearchParams({grant_type:'refresh_token',client_id:clientId,refresh_token:issued.refresh_token})
  assert.equal((await post(bounded.base,'/token',new URLSearchParams({...Object.fromEntries(refresh),scope:'mcp admin'}))).status,400)
  assert.equal((await post(bounded.base,'/token',new URLSearchParams({...Object.fromEntries(refresh),resource:'https://attacker.example/mcp'}))).status,400)
  // Expired access entries are reclaimed, not kept until process restart.
  await new Promise(r=>setTimeout(r,1100))
  const rotated=await post(bounded.base,'/token',refresh);assert.equal(rotated.status,200)
  assert.equal((await post(bounded.base,'/token',refresh)).status,400)
  assert.equal((await post(bounded.base,'/revoke',new URLSearchParams({client_id:clientId,token:secondIssued.refresh_token}))).status,200)
  assert.equal((await exchange(bounded.base,third)).status,200,'Capacity denial must not consume the authorization code')
  console.log('PASS: code/token capacity and expiry collection, scope/resource binding, refresh rotation; denied capacity does not destroy retryable grants')

  const draining=await service()
  const hanging=httpRequest(draining.base+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded','content-length':'64000'}})
  const hungClosed=new Promise(resolve=>{hanging.on('error',()=>{});hanging.once('close',resolve)})
  hanging.write('grant_type=');await new Promise(r=>setTimeout(r,40))
  await Promise.race([Promise.all([draining.server.stop(),hungClosed]),new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('Stalled OAuth body held Stop hostage')),1000);timer.unref()})])
  console.log('PASS: real unfinished OAuth body cannot keep Stop/update waiting on an active HTTP socket')

  const health=await service();await probePublicService(health.base,health.server.instanceId)
  await assert.rejects(probePublicService(health.base,'different-instance'),/different service/)
  const abort=new AbortController();abort.abort();await assert.rejects(waitForPublicService(health.base,'wrong',abort.signal,100))
  let failures=0,active=0,maximum=0,probes=0,finished
  const failed=new Promise(resolve=>{finished=resolve})
  const monitor=new NetworkHealthMonitor(async()=>{probes++;active++;maximum=Math.max(maximum,active);await new Promise(r=>setTimeout(r,20));active--;throw Error('fixture unreachable')},()=>{failures++;finished()},5)
  // Windows timers need not honor sub-16ms waits. Await the actual terminal
  // event with a bounded deadline instead of assuming three probes fit in 45ms.
  monitor.start()
  try{await Promise.race([failed,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('Three-failure shutdown did not occur')),5000);timer.unref()})])}finally{await monitor.stop()}
  assert.equal(failures,1);assert.equal(probes,3);assert.equal(maximum,1)
  console.log('PASS: owned service nonce, cancellable readiness, serial health monitoring and three-failure shutdown')

  let degraded=0,recovered,attempts=0
  const recovery=new Promise(resolve=>{recovered=resolve})
  const recovering=new NetworkHealthMonitor(async()=>{if(++attempts<=5)throw Error('fixture public outage')},()=>{degraded++},5,
    {keepRunningOnFailure:true,onProbeResult:result=>{if(result.ok)recovered()}})
  recovering.start()
  try{await Promise.race([recovery,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('Degraded monitor did not recover')),2000);timer.unref()})])}finally{await recovering.stop()}
  assert.equal(degraded,1);assert.ok(attempts>=6)
  console.log('PASS: recoverable public outage reports degradation once and continues probing until recovery instead of terminating the monitor')

  const updateEvents=[],updateLocks=[],updateState=emptyUpdateState();let rejectDownload=false
  const updatePackage={version:'99.0.0',close:async()=>{},download:async()=>{updateEvents.push('download');if(rejectDownload)throw Error('fixture signature rejected')},install:async()=>{updateEvents.push('install')}}
  const updates=createUpdateController(updateState,{check:async()=>updatePackage,stopRuntime:async()=>{updateEvents.push('stop')},relaunch:async()=>{updateEvents.push('restart')},installationLock:value=>updateLocks.push(value)})
  await updates.check();await updates.check();assert.equal(updateState.phase,'available');assert.deepEqual(updateEvents,[]);assert.deepEqual(updateLocks,[])
  rejectDownload=true;await updates.install();assert.equal(updateState.phase,'error');assert.deepEqual(updateEvents,['download']);assert.equal(updateLocks.at(-1),false)
  updateEvents.length=0;rejectDownload=false;await updates.install();assert.deepEqual(updateEvents,['download','stop','install','restart']);assert.equal(updateState.phase,'installed')
  console.log('PASS: update checks never download/stop/install/restart; explicit installation alone runs that sequence and download/signature failure keeps existing work intact (updater contract fixture)')

  const unrelated={TCP:{'8443':{HTTPS:true}},Web:{'user.ts.net:8443':{Handlers:{'/':{Proxy:'http://127.0.0.1:9999'}}}},AllowFunnel:{'user.ts.net:8443':true}}
  let state=structuredClone(unrelated);const commands=[]
  const command=async args=>{
    commands.push(args)
    if(args.includes('status'))return JSON.stringify(state)
    assert.ok(!args.includes('reset'))
    if(args.includes('off')){delete state.TCP['443'];delete state.Web['fixture.ts.net:443'];delete state.AllowFunnel['fixture.ts.net:443']}
    else {state.TCP['443']={HTTPS:true};state.Web['fixture.ts.net:443']={Handlers:{'/':{Proxy:health.base}}};state.AllowFunnel['fixture.ts.net:443']=true}
    return ''
  }
  const tailscale=new TailscaleNetworkProvider({executable:process.execPath,publicUrl:'https://fixture.ts.net'},command)
  const context={localBaseUrl:health.base,logger,onUnexpectedExit(){throw Error('unexpected fixture failure')}}
  await tailscale.start(context);await tailscale.stop();assert.deepEqual(state,unrelated)
  state.TCP['443']={HTTPS:true};const before=commands.length
  await assert.rejects(tailscale.start(context),/refusing to overwrite/);assert.equal(commands.length,before+1)
  delete state.TCP['443'];await tailscale.start(context);state.Web['fixture.ts.net:443'].Handlers['/'].Proxy='http://127.0.0.1:1234'
  const changed=structuredClone(state);await assert.rejects(tailscale.stop(),/leaving user configuration untouched/);assert.deepEqual(state,changed)
  console.log('PASS: Tailscale CLI contract double refuses occupied port, preserves other ports, detects ownership changes; never global reset (not a live Tailscale account test)')

  let cliCreated;const cliIssued=new Promise(resolve=>{cliCreated=resolve});state=structuredClone(unrelated)
  const inFlight=new TailscaleNetworkProvider({executable:process.execPath,publicUrl:'https://fixture.ts.net'},async(args,signal)=>{
    if(args.includes('status')||args.includes('off'))return command(args)
    await command(args);cliCreated()
    return new Promise((_,reject)=>{signal.addEventListener('abort',()=>reject(signal.reason),{once:true});if(signal.aborted)reject(signal.reason)})
  })
  const starting=inFlight.start(context);const rejected=assert.rejects(starting,e=>e.name==='AbortError')
  await cliIssued
  const stopOnce=inFlight.stop();assert.equal(inFlight.stop(),stopOnce)
  await Promise.all([stopOnce,rejected]);assert.deepEqual(state,unrelated)
  console.log('PASS: Tailscale in-flight CLI is aborted/drained before concurrent Stop inspects and removes the owned candidate; unrelated routes retained (CLI contract fixture)')

  const cancellable=new ManagedProcess(logger);cleanups.push(()=>cancellable.stop())
  cancellable.start(process.execPath,['-e',"console.log('waiting');setInterval(()=>{},1000)"],'abort-readiness')
  await cancellable.waitFor(line=>line==='waiting',2000,'fixture startup')
  const waitingAbort=new AbortController(),waiting=cancellable.waitFor(()=>false,60000,'never-ready',waitingAbort.signal)
  const cancelled=assert.rejects(waiting,e=>e.name==='AbortError');waitingAbort.abort();await cancelled;await cancellable.stop()
  console.log('PASS: real process readiness cancellation does not wait for a 60-second timeout; owned process closes without reporting failure')

  {
    const markerFile=path.join(directory,'owned-tunnel-descendant.txt')
    const childCode=`require('node:fs').writeFileSync(${JSON.stringify(markerFile)},'alive');process.on('SIGTERM',()=>{});setInterval(()=>require('node:fs').appendFileSync(${JSON.stringify(markerFile)},'x'),20);`
    // Keep the Windows leader alive: taskkill /T owns a live PID tree, not
    // arbitrary orphan/breakaway processes. Unix also tests leader exit.
    const leader=`require('node:child_process').spawn(process.execPath,['-e',${JSON.stringify(childCode)}],{stdio:'ignore'});console.log('first');console.log('registered');${process.platform==='win32'?'setInterval(()=>{},1000);':'setTimeout(()=>process.exit(0),100);'}`
    const managed=new ManagedProcess(logger);cleanups.push(()=>managed.stop())
    managed.start(process.execPath,['-e',leader],'owned-descendant')
    await managed.waitFor(line=>line==='first',2000,'first fixture line')
    const markerDeadline=Date.now()+5000
    while(Date.now()<markerDeadline){if(await stat(markerFile).catch(()=>undefined))break;await new Promise(r=>setTimeout(r,50))}
    assert.ok(await stat(markerFile).catch(()=>undefined),'Owned descendant must actually start before cleanup is tested')
    await new Promise(r=>setTimeout(r,250))
    assert.equal(managed.running,process.platform==='win32')
    await managed.stop()
    const before=(await stat(markerFile)).size;await new Promise(r=>setTimeout(r,120));assert.equal((await stat(markerFile)).size,before)
    console.log(process.platform==='win32'?'PASS: actual Windows owned live PID tree cleaned by taskkill /T; independent descendant marker stops (not an orphan/breakaway guarantee)':'PASS: actual Unix owned tunnel process group cleaned after leader exit, including TERM-ignoring descendant')
  }

  // Actual Runtime/listener, with only public transport and provider exit
  // injected. A remote probe outage must not dispose the local execution host.
  const reservation=reservePort();await new Promise(resolve=>reservation.listen(0,'127.0.0.1',resolve))
  const port=reservation.address().port;await new Promise(resolve=>reservation.close(resolve))
  const local=`http://127.0.0.1:${port}`,originalFetch=globalThis.fetch,originalStart=NetworkHealthMonitor.prototype.start,originalProviderStart=ExternalNetworkProvider.prototype.start
  let exitProvider
  const liveRuntime=new RuntimeSupervisor({...loadConfig({MICROMATRIX_CONFIG_FILE:path.join(directory,'health-runtime.json'),MICROMATRIX_WORKSPACE:directory,MICROMATRIX_NETWORK_PROVIDER:'external',MICROMATRIX_PUBLIC_URL:local,MICROMATRIX_PORT:String(port)}),network:{provider:'external',publicUrl:local,options:{}}},logger)
  cleanups.push(()=>liveRuntime.dispose())
  const until=async predicate=>{const deadline=Date.now()+2000;while(!predicate()){if(Date.now()>deadline)throw Error('Runtime health fixture exceeded deadline');await new Promise(resolve=>setTimeout(resolve,10))}}
  try{
    NetworkHealthMonitor.prototype.start=function(){Object.defineProperty(this,'intervalMs',{value:5});originalStart.call(this)}
    ExternalNetworkProvider.prototype.start=function(context){exitProvider=context.onUnexpectedExit;return originalProviderStart.call(this,context)}
    await liveRuntime.start()
    globalThis.fetch=async(input,init)=>String(input).startsWith(local)?new Response('',{status:502}):originalFetch(input,init)
    await until(()=>liveRuntime.snapshot().networkWarning.includes('HTTP 502'))
    assert.equal(liveRuntime.snapshot().running,true);assert.equal(liveRuntime.snapshot().extensionHostActive,true);assert.equal(liveRuntime.snapshot().publicMcpUrl,'');assert.equal(liveRuntime.snapshot().exitReason,'')
    assert.equal((await originalFetch(local+'/healthz')).status,200)
    globalThis.fetch=originalFetch;await until(()=>liveRuntime.snapshot().networkWarning==='');assert.equal(liveRuntime.snapshot().publicMcpUrl,local+'/mcp')
    exitProvider(Error('fixture provider actually exited'))
    await until(()=>!liveRuntime.snapshot().extensionHostActive);await liveRuntime.stop()
    assert.equal(liveRuntime.snapshot().running,false);assert.ok(liveRuntime.snapshot().exitReason.includes('fixture provider actually exited'))
    await assert.rejects(originalFetch(local+'/healthz'))
  }finally{globalThis.fetch=originalFetch;NetworkHealthMonitor.prototype.start=originalStart;ExternalNetworkProvider.prototype.start=originalProviderStart;await liveRuntime.dispose()}
  console.log('PASS: actual Runtime survives repeated public 502 responses, preserves its local listener/host, recovers its URL; actual provider-exit notification still disposes execution (injected network/exit events)')

  // Save/browser configuration via the actual supervisor must remain idle.
  const runtime=new RuntimeSupervisor(loadConfig({MICROMATRIX_CONFIG_FILE:path.join(directory,'runtime.json'),MICROMATRIX_WORKSPACE:directory,MICROMATRIX_NETWORK_PROVIDER:'frp',MICROMATRIX_PORT:'8222'}),logger)
  cleanups.push(()=>runtime.dispose())
  const browser={endpoint:'ws://127.0.0.1:9222/devtools/browser/fixture',allowedOrigins:['https://example.com']}
  await runtime.configureComputerUseBrowser(browser)
  assert.equal(runtime.snapshot().running,false);assert.deepEqual(runtime.computerUseStatus().browser,browser)
  assert.deepEqual(JSON.parse(await readFile(path.join(directory,'runtime.json'),'utf8')).computerUse.browser,browser)
  await assert.rejects(runtime.configureComputerUseBrowser({...browser,endpoint:'ws://remote.example/devtools/browser/a'}))
  assert.deepEqual(runtime.computerUseStatus().browser,browser)
  await runtime.configureComputerUseBrowser(null);assert.equal(runtime.computerUseStatus().browser,undefined)
  assert.equal(runtime.snapshot().running,false)
  console.log('PASS: browser Save/clear validates and persists without connecting browser, running MCP/Tunnel or wiping unrelated Computer Use settings')
}finally{
  CimdClientResolver.prototype.resolve=savedResolve
  for(const cleanup of cleanups.reverse())await cleanup()
  await rm(directory,{recursive:true,force:true})
}
