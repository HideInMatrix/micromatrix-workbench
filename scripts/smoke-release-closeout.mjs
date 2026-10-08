import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import {catalogNotices,rustStandardLibraryNotice} from './dependency-notices.mjs'
import {cloudflareConnectionError} from '../packages/network/dist/cloudflare.js'

if(process.argv.length>2)throw Error('Closeout smoke takes no arguments')
const hash=b=>createHash('sha256').update(b).digest('hex'),root=process.cwd(),catalog=JSON.parse(readFileSync('third_party/dependencies/manifest.json'))
for(const entry of catalog.notices){assert.equal(hash(readFileSync(path.join(root,'third_party/dependencies',entry.file))),entry.sha256);assert.ok(entry.source.startsWith('https://'));if(entry.ecosystem==='cargo')assert.match(entry.vcsCommit,/^[a-f0-9]{40}$/);if(entry.basis==='upstream-declaration-and-standard-text')assert.ok(entry.file.includes('NOTICE'))}
const directory=mkdtempSync(path.join(os.tmpdir(),'mm-notice-integrity-')),notices=path.join(directory,'third_party/dependencies'),crate=path.join(directory,'crate'),text='reviewed fixture declaration + licence text'
try{
 mkdirSync(notices,{recursive:true});mkdirSync(crate);writeFileSync(path.join(crate,'.cargo_vcs_info.json'),JSON.stringify({git:{sha1:'a'.repeat(40)}}))
 const entry={ecosystem:'cargo',name:'fixture',version:'1.0.0',license:'MIT',vcsCommit:'a'.repeat(40),file:'NOTICE',source:'https://example.com/upstream',sha256:hash(text)}
 const standard={version:'1.98.1',compilerCommit:'b'.repeat(40),file:'RUST.html',sha256:hash(text)}
 const manifestFile=path.join(notices,'manifest.json');writeFileSync(manifestFile,JSON.stringify({notices:[entry],rustStandardLibrary:standard}));writeFileSync(path.join(notices,'NOTICE'),text);writeFileSync(path.join(notices,'RUST.html'),text)
 const pkg={name:'fixture',version:'1.0.0',license:'MIT'}
 assert.equal(catalogNotices(directory,'cargo',pkg,crate).length,1);assert.equal(catalogNotices(directory,'cargo',{...pkg,version:'2.0.0'},crate).length,0)
 writeFileSync(path.join(crate,'.cargo_vcs_info.json'),JSON.stringify({git:{sha1:'c'.repeat(40)}}));assert.throws(()=>catalogNotices(directory,'cargo',pkg,crate),/source changed/)
 writeFileSync(path.join(crate,'.cargo_vcs_info.json'),JSON.stringify({git:{sha1:'a'.repeat(40)}}));writeFileSync(path.join(notices,'NOTICE'),text+'tampered');assert.throws(()=>catalogNotices(directory,'cargo',pkg,crate),/hash changed/)
 const compiler=`release: 1.98.1\ncommit-hash: ${standard.compilerCommit}\n`
 assert.equal(rustStandardLibraryNotice(directory,path.join(directory,'minimal-profile'),compiler),path.join(notices,'RUST.html'))
 assert.equal(rustStandardLibraryNotice(directory,path.join(directory,'minimal-profile'),compiler.replace('1.98.1','1.99.0')),undefined)
 writeFileSync(path.join(notices,'RUST.html'),text+'tampered');assert.throws(()=>rustStandardLibraryNotice(directory,path.join(directory,'minimal-profile'),compiler),/notice changed/)
 console.log('PASS: all reviewed notice hashes; catalogue version/commit/integrity rejection; minimal-profile Rust fallback refuses wrong compiler or tampered notice')
}finally{rmSync(directory,{recursive:true,force:true})}
const original=new Error('original upstream timeout'),fake=cloudflareConnectionError(['ip=198.18.0.42 token=must-not-appear'],original),blocked=cloudflareConnectionError(['precheck component="TCP Connectivity" status=fail'],original)
assert.match(fake.message,/fake-IP/);assert.equal(fake.cause,original);assert.ok(!fake.message.includes('must-not-appear'));assert.match(blocked.message,/7844/);assert.equal(blocked.cause,original);assert.equal(cloudflareConnectionError(['normal output'],original),original)
console.log('PASS: known real Cloudflare network failure patterns have fixed redacted guidance and retain the original cause; unknown failures are not reclassified')
