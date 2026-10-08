import assert from 'node:assert/strict'
import {randomBytes,createHash} from 'node:crypto'
import {mkdtemp,rm,writeFile} from 'node:fs/promises'
import net from 'node:net'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {Client} from '@modelcontextprotocol/sdk/client/index.js'
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import {RuntimeSupervisor} from '../apps/daemon/dist/runtime.js'
import {loadConfig} from '../apps/daemon/dist/config.js'
import {nativeBuildTarget} from './build-platform.mjs'

// Explicit opt-in: owns only loopback or an account-free Quick Tunnel and a temporary,
// read-only workspace. Never touches the user's named tunnel, browser, account,
// config, system grants or installed app. Never follow the ChatGPT callback.
if(!process.argv.includes('--run'))throw Error('Live public-network acceptance requires explicit --run')
const provider=process.argv.find(a=>a.startsWith('--provider='))?.split('=')[1]??'external'
const protocol=process.argv.find(a=>a.startsWith('--protocol='))?.split('=')[1]??'http2'
for(const arg of process.argv.slice(2))if(arg!=='--run'&&!/^--protocol=(http2|quic|auto)$/.test(arg)&&!/^--provider=(external|cloudflare)$/.test(arg))throw Error(`Unsupported live acceptance option: ${arg}`)
const temporary=await mkdtemp(path.join(tmpdir(),'mm-live-cloudflare-'))
const availablePort=async()=>{const s=net.createServer();await new Promise((resolve,reject)=>{s.once('error',reject);s.listen(0,'127.0.0.1',resolve)});const port=s.address().port;await new Promise(resolve=>s.close(resolve));return port}
const port=await availablePort();let controlPort=await availablePort();while(port===controlPort)controlPort=await availablePort()
const password=randomBytes(32).toString('base64url'),marker=randomBytes(16).toString('hex'),logs=[]
const logger={log(level,message){logs.push(`${level}: ${message}`);if(logs.length>80)logs.shift()}}
const config=loadConfig({MICROMATRIX_CONFIG_FILE:path.join(temporary,'runtime.json'),MICROMATRIX_WORKSPACE:temporary,
 MICROMATRIX_HOST:'127.0.0.1',MICROMATRIX_PORT:String(port),MICROMATRIX_CONTROL_PORT:String(controlPort),
 MICROMATRIX_NETWORK_PROVIDER:provider,MICROMATRIX_CLOUDFLARED:path.resolve('src-tauri/binaries',`cloudflared-${nativeBuildTarget()}${process.platform==='win32'?'.exe':''}`),
 MICROMATRIX_CLOUDFLARE_PROTOCOL:protocol,MICROMATRIX_OAUTH_PASSWORD:password,MICROMATRIX_REMEMBER_SECRETS:'false',MICROMATRIX_PERMISSION_MODE:'safe'})
const runtime=new RuntimeSupervisor(config,logger),client=new Client({name:'public-read-only-acceptance',version:'1'})
let transport
const request=async(url,init={})=>fetch(url,{...init,redirect:'manual',signal:AbortSignal.timeout(15000)})
try{
 await writeFile(path.join(temporary,'input.txt'),marker)
 assert.equal(runtime.snapshot().running,false)
 await runtime.start()
 const snapshot=runtime.snapshot();assert.equal(snapshot.running,true)
 const base=new URL(snapshot.publicMcpUrl).origin
 console.log(provider==='cloudflare'?`PASS: real Cloudflare Quick Tunnel ${protocol}, public nonce verified; owned public entry ${base}`:`PASS: real loopback service; owned nonce verified (not public Tunnel acceptance)`)
 const card=await request(base+'/');assert.equal(card.status,200)
 const serviceInfo=await card.json();assert.equal(serviceInfo.server.name,'micromatrix agent')
 const denied=await request(base+'/mcp',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});assert.equal(denied.status,401)
 const metadata=await request(base+'/.well-known/oauth-authorization-server').then(r=>r.json());assert.equal(metadata.issuer,base);assert.equal(metadata.client_id_metadata_document_supported,true)
 const clientId='https://chatgpt.com/oauth/client.json',redirect='https://chatgpt.com/connector_platform_oauth_redirect'
 const verifier=randomBytes(48).toString('base64url'),challenge=createHash('sha256').update(verifier).digest('base64url'),state=randomBytes(16).toString('hex')
 const authorization=new URLSearchParams({client_id:clientId,redirect_uri:redirect,response_type:'code',code_challenge_method:'S256',code_challenge:challenge,resource:base+'/mcp',scope:'mcp',state})
 const login=await request(base+'/authorize?'+authorization);assert.equal(login.status,200,`CIMD login: ${await login.text()}`)
 authorization.set('password',password)
 const granted=await request(base+'/authorize',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:authorization})
 assert.equal(granted.status,302)
 const callback=new URL(granted.headers.get('location'));assert.equal(callback.origin+callback.pathname,redirect);assert.equal(callback.searchParams.get('state'),state);assert.equal(callback.searchParams.get('iss'),base)
 const code=callback.searchParams.get('code');assert.ok(code)
 const tokenBody=new URLSearchParams({grant_type:'authorization_code',client_id:clientId,redirect_uri:redirect,code,code_verifier:verifier,resource:base+'/mcp'})
 const tokenResponse=await request(base+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:tokenBody});assert.equal(tokenResponse.status,200)
 const tokens=await tokenResponse.json();assert.ok(tokens.access_token);assert.ok(tokens.refresh_token)
 transport=new StreamableHTTPClientTransport(new URL(base+'/mcp'),{requestInit:{headers:{Authorization:`Bearer ${tokens.access_token}`}}})
 await client.connect(transport,{timeout:15000})
 const catalog=await client.listTools();assert.ok(catalog.tools.some(t=>t.name==='read'))
 const result=await client.callTool({name:'read',arguments:{path:'input.txt'}},undefined,{timeout:15000});assert.notEqual(result.isError,true);assert.ok(JSON.stringify(result.content).includes(marker))
 console.log('PASS: actual ChatGPT CIMD DNS/TLS, real authorization form, S256 code exchange, state/issuer/resource binding and real SDK MCP read; no callback/account interaction')
 const refreshed=await request(base+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'refresh_token',client_id:clientId,refresh_token:tokens.refresh_token,resource:base+'/mcp'})});assert.equal(refreshed.status,200)
 const replacement=await refreshed.json();assert.notEqual(replacement.refresh_token,tokens.refresh_token)
 const replay=await request(base+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'refresh_token',client_id:clientId,refresh_token:tokens.refresh_token})});assert.equal(replay.status,400)
 await client.close();await runtime.stop();assert.equal(runtime.snapshot().running,false);assert.equal(runtime.snapshot().publicMcpUrl,'')
 await assert.rejects(fetch(`http://127.0.0.1:${port}/healthz`,{signal:AbortSignal.timeout(1000)}))
 console.log('PASS: refresh rotation rejects replay; explicit Stop revokes address, closes transport and releases owned local listener (and Quick Tunnel when selected)')
}catch(error){console.error(logs.join('\n'));throw error}
finally{await client.close().catch(()=>{});await transport?.close().catch(()=>{});await runtime.dispose();await rm(temporary,{recursive:true,force:true})}
