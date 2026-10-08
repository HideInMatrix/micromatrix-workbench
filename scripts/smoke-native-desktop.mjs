import assert from 'node:assert/strict'
import {execFileSync,spawn} from 'node:child_process'
import {mkdtemp,writeFile,readFile,rm,mkdir} from 'node:fs/promises'
import {once} from 'node:events'
import path from 'node:path'
import {tmpdir} from 'node:os'
import {randomUUID} from 'node:crypto'
import {Client} from '@modelcontextprotocol/sdk/client/index.js'
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js'

// Native acceptance owns ONE disposable GUI, not Blender or personal apps.
// Explicit opt-in; no permission prompt, elevation or clipboard/screen capture.
const args=process.argv.slice(2),flag=args.indexOf('--service-executable')
if(!args.includes('--run')||flag<0||!args[flag+1])throw Error('Use --run --service-executable <signed packaged service> [--require-desktop]')
for(let i=0;i<args.length;i++){if(args[i]==='--service-executable'){i++;continue}if(!['--run','--require-desktop'].includes(args[i]))throw Error(`Unsupported native acceptance option: ${args[i]}`)}
if(!['darwin','win32'].includes(process.platform))throw Error('Native acceptance supports macOS and Windows only')
const directory=await mkdtemp(path.join(tmpdir(),'mm-native-gui-')),stateFile=path.join(directory,'state.json'),readyFile=path.join(directory,'ready.json'),marker='native-'+randomUUID()
const client=new Client({name:'owned-native-fixture-acceptance',version:'1'}),transport=new StdioClientTransport({command:path.resolve(args[flag+1]),args:['--computer-use-mcp','--allow-actions'],cwd:directory,stderr:'pipe'})
let launcher,fixturePid=0
const result=async(name,arguments_={})=>{const r=await client.callTool({name,arguments:arguments_},undefined,{timeout:20000});assert.notEqual(r.isError,true,JSON.stringify(r.content));return JSON.parse(r.content[0].text)}
async function waitJson(file){const deadline=Date.now()+15000;while(Date.now()<deadline){try{return JSON.parse(await readFile(file,'utf8'))}catch{}await new Promise(r=>setTimeout(r,80))}throw Error('Owned native GUI did not become ready')}
try{
 await client.connect(transport)
 const permissions=await result('computer_permissions',{request:false})
 assert.equal(permissions.prompt_requested,false)
 if(process.platform==='darwin'&&permissions.screen_recording===false){
  assert.ok(Number.isSafeInteger(permissions.pid)&&permissions.pid>1)
  // Owned helper PID only. Permission is checked before window capture, so
  // this negative test remains safe even when the interactive session locks.
  const denied=await client.callTool({name:'computer_observe',arguments:{adapter:'desktop-visual',target:`pid:${permissions.pid}`}},undefined,{timeout:20000})
  assert.equal(denied.isError,true);assert.match(JSON.stringify(denied.content),/SCREEN_RECORDING_PERMISSION_REQUIRED/)
  assert.ok(!denied.content.some(part=>part.type==='image'))
  console.log('PASS: actual missing Screen Recording refuses capture without an image or silent permission prompt')
 }
 const interactive=process.platform==='darwin'
  ?execFileSync('/usr/bin/swift',['-e','import ApplicationServices; import AppKit; let d=CGSessionCopyCurrentDictionary() as? [String:Any] ?? [:]; let locked=d["CGSSessionScreenIsLocked"] as? Bool ?? false; print((d["kCGSSessionOnConsoleKey"] as? Bool ?? false) && (d["kCGSessionLoginDoneKey"] as? Bool ?? false) && !locked && NSWorkspace.shared.frontmostApplication?.bundleIdentifier != "com.apple.loginwindow" ? "available" : "unavailable")'],{timeout:60000,encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim()==='available'
  :permissions.interactive_desktop===true
 const authorized=interactive&&(process.platform!=='darwin'||permissions.accessibility===true)
 console.log('Native permission check:',JSON.stringify(permissions))
 if(!authorized){if(args.includes('--require-desktop'))throw Error('Native fixture requires an already authorized, unlocked interactive desktop; no permission requested and no unlock attempted');console.log('UNVERIFIED: native UI input skipped because this runner has no granted/unlocked interactive desktop; not counted as a GUI PASS')}
 else{
  if(process.platform==='darwin'){
   const application=path.join(directory,'Micromatrix Acceptance.app'),contents=path.join(application,'Contents'),bin=path.join(contents,'MacOS/mm-fixture')
   await mkdir(path.dirname(bin),{recursive:true})
   await writeFile(path.join(contents,'Info.plist'),`<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>org.micromatrix.acceptance.fixture.${randomUUID()}</string><key>CFBundleExecutable</key><string>mm-fixture</string><key>CFBundleName</key><string>Micromatrix Acceptance</string><key>CFBundlePackageType</key><string>APPL</string><key>NSPrincipalClass</key><string>NSApplication</string></dict></plist>`)
   const source=path.join(directory,'fixture.swift')
   await writeFile(source,`import AppKit
import Foundation
final class Fixture: NSObject, NSApplicationDelegate {
 var window: NSWindow!
 var field: NSTextField!
 var timer: Timer!
 func persist(){let data=try! JSONSerialization.data(withJSONObject:["pid":ProcessInfo.processInfo.processIdentifier,"value":field.stringValue,"windows":NSApp.windows.count,"visible":window.isVisible,"window_role":window.accessibilityRole()?.rawValue ?? "none","field_role":field.accessibilityRole()?.rawValue ?? "none"]);try! data.write(to:URL(fileURLWithPath:CommandLine.arguments[1]),options:.atomic)}
 func applicationDidFinishLaunching(_ notification: Notification){
  window=NSWindow(contentRect:NSRect(x:250,y:250,width:400,height:120),styleMask:[.titled,.closable],backing:.buffered,defer:false)
  window.isReleasedWhenClosed=false
  window.title="Micromatrix isolated acceptance"
  field=NSTextField(frame:NSRect(x:20,y:40,width:350,height:30))
  field.stringValue="pending"
  field.setAccessibilityLabel("Acceptance Value")
  field.setAccessibilityIdentifier("acceptance-value")
  field.setAccessibilityElement(true)
  field.setAccessibilityRole(.textField)
  window.contentView!.addSubview(field)
  window.makeKeyAndOrderFront(nil)
  NSApplication.shared.activate(ignoringOtherApps:true)
  persist()
  try! JSONSerialization.data(withJSONObject:["pid":ProcessInfo.processInfo.processIdentifier]).write(to:URL(fileURLWithPath:CommandLine.arguments[2]),options:.atomic)
  timer=Timer.scheduledTimer(withTimeInterval:0.1,repeats:true){[weak self] _ in self?.persist()}
 }
}
let app=NSApplication.shared
let fixture=Fixture()
app.setActivationPolicy(.regular)
app.delegate=fixture
app.run()
withExtendedLifetime(fixture){}
`)

   execFileSync('swiftc',[source,'-o',bin],{timeout:60000,stdio:'pipe'})
   execFileSync('codesign',['--sign','-',application],{timeout:10000,stdio:'pipe'})
   launcher=spawn('/usr/bin/open',['-n','-W','-a',application,'--args',stateFile,readyFile],{stdio:'ignore'})
  }else{
   const source=path.join(directory,'fixture.cs'),bin=path.join(directory,'mm-fixture.exe'),windows=process.env.WINDIR||'C:\\Windows'
   await writeFile(source,`using System;using System.IO;using System.Windows.Forms;class Fixture{[STAThread]static void Main(string[] args){Application.EnableVisualStyles();var form=new Form{Text="Micromatrix isolated acceptance",Width=400,Height=150};var field=new TextBox{AccessibleName="Acceptance Value",Text="pending",Left=20,Top=30,Width=340};form.Controls.Add(field);Action save=()=>File.WriteAllText(args[0],"{\\\"value\\\":"+new System.Web.Script.Serialization.JavaScriptSerializer().Serialize(field.Text)+"}");field.TextChanged+=(s,e)=>save();form.Shown+=(s,e)=>{save();File.WriteAllText(args[1],"{\\\"pid\\\":"+System.Diagnostics.Process.GetCurrentProcess().Id+"}");};Application.Run(form);}}`)
   execFileSync(path.join(windows,'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),['/nologo','/target:winexe','/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll',`/out:${bin}`,source],{timeout:60000,stdio:'pipe',windowsHide:true})
   launcher=spawn(bin,[stateFile,readyFile],{stdio:'ignore',windowsHide:false})
  }
  const ready=await waitJson(readyFile);fixturePid=ready.pid;assert.ok(Number.isSafeInteger(fixturePid)&&fixturePid>1)
  const target=`pid:${fixturePid}`
  // The ready file precedes the native event loop. Wait only for owned-fixture
  // read-only readiness; never retry a mutation or reuse an old observation.
  const initial=await result('computer_observe',{adapter:'desktop',target})
  if(initial.app_state.active!==true){const activation=await result('computer_act',{observation_id:initial.meta.observation_id,action_type:'navigate',target:`app:${fixturePid}`,params:{}});assert.equal(activation.execution,'executed')}
  const readyDeadline=Date.now()+10000;let observed
  do{observed=await result('computer_observe',{adapter:'desktop',target});if(observed.interactive_elements.some(n=>n.editable&&n.value==='pending'&&n.available_actions.includes('set_value')))break;await new Promise(r=>setTimeout(r,150))}while(Date.now()<readyDeadline)
  assert.equal(observed.meta.source,process.platform==='darwin'?'macos_accessibility':'windows_uiautomation')
  console.log("Owned fixture read-only state:",JSON.stringify(await waitJson(stateFile)))
  assert.ok(observed.interactive_elements.some(n=>n.editable&&n.value==='pending'&&n.available_actions.includes('set_value')),`Owned fixture did not expose its field: ${JSON.stringify({app_state:observed.app_state,environment:observed.environment,controls:observed.interactive_elements.filter(n=>["AXWindow","AXTextField","Edit"].includes(n.type))})}`)
  const batch=await result('computer_run',{code:`const s=await computer.observe({adapter:'desktop',target:${JSON.stringify(target)}});const n=s.interactive_elements.find(n=>n.editable&&n.value==='pending'&&n.available_actions.includes('set_value'));if(!n)return {fixture_not_ready:true,elements:s.interactive_elements};const r=await computer.act({observation_id:s.meta.observation_id,action_type:'set_value',target:n.id,params:{value:${JSON.stringify(marker)}},expect_observation:{target:n.id,value:${JSON.stringify(marker)}}});return {execution:r.execution,verification:r.verification};`})
  assert.notEqual(batch.result.fixture_not_ready,true,JSON.stringify(batch.result))
  assert.equal(batch.result.execution,'executed');assert.equal(batch.result.verification.status,'passed')
  const deadline=Date.now()+3000;let state
  while(Date.now()<deadline){state=await waitJson(stateFile);if(state.value===marker)break;await new Promise(r=>setTimeout(r,100))}
  assert.equal(state.value,marker,'Independent fixture process must observe the actual GUI mutation')
  const readback=await result('computer_observe',{adapter:'desktop',target});assert.ok(readback.interactive_elements.some(n=>n.value===marker))
  console.log(`PASS: actual ${process.platform==='darwin'?'AppKit/Accessibility':'WinForms/UIAutomation'} GUI + packaged MCP/QuickJS semantic set_value, independent fixture readback; no personal app modified`)
 }
}finally{
 await client.close().catch(()=>{});await transport.close().catch(()=>{})
 if(fixturePid>1)try{process.kill(fixturePid,'SIGTERM')}catch{}
 if(launcher&&launcher.exitCode===null){await Promise.race([once(launcher,'exit'),new Promise(r=>setTimeout(r,1000))]);if(launcher.exitCode===null)launcher.kill('SIGKILL')}
 await rm(directory,{recursive:true,force:true})
}
