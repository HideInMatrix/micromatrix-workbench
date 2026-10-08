import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {once} from 'node:events'
import {createHash,randomUUID} from 'node:crypto'
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {createRequire} from 'node:module'
import {spawnSync} from 'node:child_process'
import {auth} from '@modelcontextprotocol/sdk/client/auth.js'
import {OAuthTokensSchema,OAuthClientInformationSchema} from '@modelcontextprotocol/sdk/shared/auth.js'
import {McpAuthStore} from '../plugins/mcp/dist/auth.js'
import {parseMcpConnection} from '../packages/plugin-kit/dist/resources.js'

// Real installed SDK + local HTTP/PKCE + private files. No remote OAuth account,
// real token, browser, desktop input or system permission is involved.
const require=createRequire(import.meta.url)
const sdkPackage=JSON.parse(await readFile(path.resolve(path.dirname(require.resolve('@modelcontextprotocol/sdk/client/auth.js')),'../../../package.json'),'utf8'))
assert.equal(sdkPackage.version,'1.32.1')
assert.equal(require('source-map-js/package.json').version,'1.2.2')
const directory=await mkdtemp(path.join(tmpdir(),'mm-security-regression-')),file=path.join(directory,'credentials.json')
const marker=randomUUID(),clientId='https://client.example/oauth/client.json',refresh=`fixture-refresh-${marker}`
const requests=[],codes=new Map();let selected='a',origin,sequence=0,cimd=true,store
const server=createServer(async(req,res)=>{
  try {
    const url=new URL(req.url,origin);let body=''
    for await(const chunk of req){body+=chunk;if(body.length>16384)throw Error('Fixture request too large')}
    requests.push({path:url.pathname,body})
    res.setHeader('cache-control','no-store')
    const json=value=>{res.setHeader('content-type','application/json');res.end(JSON.stringify(value))}
    if(url.pathname.startsWith('/.well-known/oauth-protected-resource')) return json({resource:`${origin}/mcp`,authorization_servers:[`${origin}/${selected}`],scopes_supported:['mcp']})
    const metadata=url.pathname.match(/^\/\.well-known\/oauth-authorization-server\/(a|b)$/)
    if(metadata){const authority=metadata[1];return json({issuer:`${origin}/a`, // b lies about issuer; SDK must bind to the actual discovery destination.
      authorization_endpoint:`${origin}/${authority}/authorize`,token_endpoint:`${origin}/${authority}/token`,response_types_supported:['code'],
      grant_types_supported:['authorization_code','refresh_token'],code_challenge_methods_supported:['S256'],token_endpoint_auth_methods_supported:['none'],
      client_id_metadata_document_supported:cimd,authorization_response_iss_parameter_supported:true})}
    if(url.pathname==='/a/authorize'){
      assert.equal(url.searchParams.get('client_id'),clientId);assert.equal(url.searchParams.get('code_challenge_method'),'S256')
      const code=randomUUID();codes.set(code,{challenge:url.searchParams.get('code_challenge'),redirect:url.searchParams.get('redirect_uri')})
      const callback=new URL(url.searchParams.get('redirect_uri'));callback.searchParams.set('code',code);callback.searchParams.set('state',url.searchParams.get('state'));callback.searchParams.set('iss',`${origin}/a`)
      res.writeHead(302,{location:callback.href}).end();return
    }
    if(url.pathname==='/a/token'){
      const form=new URLSearchParams(body);assert.equal(form.get('client_id'),clientId)
      if(form.get('grant_type')==='authorization_code'){
        const issued=codes.get(form.get('code'));assert.ok(issued);assert.equal(form.get('redirect_uri'),issued.redirect)
        assert.equal(createHash('sha256').update(form.get('code_verifier')).digest('base64url'),issued.challenge);codes.delete(form.get('code'))
      }else{assert.equal(form.get('grant_type'),'refresh_token');assert.equal(form.get('refresh_token'),refresh)}
      return json({access_token:`fixture-access-${++sequence}`,token_type:'Bearer',refresh_token:refresh,expires_in:3600,issuer:`${origin}/b`})
    }
    res.writeHead(404).end()
  }catch{res.writeHead(500).end('Fixture assertion failed')}
})
const callbackProbe=createServer()
try {
  server.listen(0,'127.0.0.1');await once(server,'listening');origin=`http://127.0.0.1:${server.address().port}`
  callbackProbe.listen(0,'127.0.0.1');await once(callbackProbe,'listening');const callback=`http://127.0.0.1:${callbackProbe.address().port}/oauth/callback`
  await new Promise(resolve=>callbackProbe.close(resolve))
  const config=parseMcpConnection({id:'security',transport:'http',auth:'oauth',url:`${origin}/mcp`,clientMetadataUrl:clientId,oauthRedirectUri:callback})
  store=new McpAuthStore(file,true);store.update(config,{LOCAL_HEADER:`fixture-header-${marker}`})
  const begin=await store.begin(config),consent=await fetch(begin.url,{redirect:'manual'});assert.equal(consent.status,302)
  const exchange=await fetch(consent.headers.get('location'));assert.equal(exchange.status,200)
  let provider=store.provider(config),client=await provider.clientInformation(),tokens=await provider.tokens()
  assert.equal(client.issuer,`${origin}/a`);assert.equal(tokens.issuer,`${origin}/a`)
  assert.equal(OAuthTokensSchema.parse(tokens).issuer,tokens.issuer);assert.equal(OAuthClientInformationSchema.parse(client).issuer,client.issuer)
  assert.throws(()=>provider.saveTokens({...tokens,issuer:undefined}),/issuer/)
  store.close();store=new McpAuthStore(file,true);provider=store.provider(config)
  assert.equal(await auth(provider,{serverUrl:config.url,fetchFn:store.fetchOAuth}),'AUTHORIZED')
  assert.equal(requests.filter(r=>r.path==='/a/token').length,2,'Same issuer must still refresh after restart')
  assert.equal((await provider.tokens()).issuer,`${origin}/a`)

  store.close();selected='b';store=new McpAuthStore(file,true);provider=store.provider(config)
  await assert.rejects(auth(provider,{serverUrl:config.url,fetchFn:store.fetchOAuth}),/authorization server changed/)
  assert.ok(requests.some(r=>r.path.endsWith('/oauth-authorization-server/b')))
  assert.ok(!requests.some(r=>r.path==='/b/token'))
  assert.ok(!requests.some(r=>r.path.startsWith('/b')&&r.body.includes(refresh)))
  assert.equal((await provider.tokens()).issuer,`${origin}/a`)
  console.log('PASS: actual SDK CIMD/PKCE + same-issuer refresh/restart; changed AS with spoofed metadata issuer never receives old refresh token')

  selected='a';cimd=false
  await assert.rejects(store.begin(config),/must advertise CIMD/)
  assert.ok(!requests.some(r=>r.path.endsWith('/register')),'Saving issuer information must not enable DCR fallback')
  assert.equal((await store.provider(config).tokens()).issuer,`${origin}/a`,'Failed login restores previous bound credentials')
  console.log('PASS: DCR-only discovery rejected without registration; failed interactive login preserves bound credentials')

  const saved=JSON.parse(await readFile(file,'utf8')),recordKey=Object.keys(saved)[0]
  for(const variant of ['missing_client','missing_token','both_missing','wrong_token','invalid_client']){
    const legacy=structuredClone(saved),oauth=legacy[recordKey].oauth
    if(variant==='missing_client'||variant==='both_missing')delete oauth.client.issuer
    if(variant==='missing_token'||variant==='both_missing')delete oauth.tokens.issuer
    if(variant==='wrong_token')oauth.tokens.issuer=`${origin}/b`
    if(variant==='invalid_client')oauth.client.issuer='not-a-url'
    const destination=path.join(directory,`${variant}.json`);await writeFile(destination,JSON.stringify(legacy),{mode:0o600})
    const migrated=new McpAuthStore(destination,true)
    try{assert.equal(migrated.summary(config).oauth,'logged_out');assert.equal(migrated.values(config).LOCAL_HEADER,`fixture-header-${marker}`)
      assert.throws(()=>migrated.provider(config).clientInformation(),/login/)
      const persisted=JSON.parse(await readFile(destination,'utf8'));assert.equal(persisted[recordKey].oauth,undefined);assert.equal(persisted[recordKey].values.LOCAL_HEADER,`fixture-header-${marker}`)
    }finally{migrated.close()}
  }
  console.log('PASS: unbound/mismatched legacy OAuth credentials removed and persisted; unrelated header secrets preserved')
  // Run hostile offsets in a bounded child, not the long-lived smoke process.
  const code=`const assert=require('node:assert/strict');const {SourceMapConsumer,SourceNode}=require('source-map-js');
    const basic={version:3,sources:['fixture.js'],sourcesContent:['x'],names:[],mappings:'AAAA'};
    const indexed=(line,column=0,map=basic)=>({version:3,sections:[{offset:{line,column},map}]});
    for(const value of [1e12,Infinity,NaN,-1,0.5,'100'])assert.throws(()=>new SourceMapConsumer(indexed(value)),/offset/i);
    assert.throws(()=>new SourceMapConsumer(indexed(0,Infinity)),/offset/i);
    assert.throws(()=>new SourceMapConsumer(indexed(6000000,0,indexed(6000000))),/nested|offset/i);
    assert.equal(SourceNode.fromStringWithSourceMap('x',new SourceMapConsumer(indexed(9999999))).toString(),'x');
    assert.equal(SourceNode.fromStringWithSourceMap('x',new SourceMapConsumer(basic)).toString(),'x');`
  const bounded=spawnSync(process.execPath,['--max-old-space-size=64','-e',code],{cwd:process.cwd(),timeout:3000,encoding:'utf8'})
  assert.equal(bounded.status,0,`Bounded source-map regression failed: ${bounded.error?.message??bounded.stderr}`)
  console.log('PASS: installed source-map-js rejects huge/invalid/nested offsets; large accepted offset and ordinary mapping finish within child timeout')
} finally {
  store?.close();callbackProbe.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true})
}
