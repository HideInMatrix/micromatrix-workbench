import assert from 'node:assert/strict'
import {Client} from '@modelcontextprotocol/sdk/client/index.js'
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js'
import {ComputerUseRuntime,ComputerUseError,ComputerScriptRunner,DesktopProxy,desktopPlatform,RemoteDesktopAdapter,createComputerUseServer} from '../packages/computer-use/dist/index.js'

// Native backends are explicit contract doubles, not real desktop capture/input.
// The SDK wire, runtime, image forwarding and embedded QuickJS are real.
for(const os of ['darwin','win32']) {
  const calls=[],bounds={x:-2560,y:40,width:2560,height:1440},display={target:'display:1',display_id:'1',primary:true,bounds,coordinate_space:os==='darwin'?'screen_points':'screen_pixels'}
  const packet={state:{revision:'b'.repeat(64),app_state:{pid:12,active:true,helper_session:'fixture'},interactive_elements:[{id:'native:1',type:'textbox',label:'Status',value:'pending',editable:true,children:[],available_actions:['set_value'],metadata:{secure:false}}],
    environment:{truncated:false,remote_desktop:{display,displays:[display],windows:[{id:'99',pid:12,title:'Fixture',z_order:0,bounds}],window_count:1,windows_truncated:false,structure_scope:'foreground_application_only',native_revision:'b'.repeat(64),layout_coordinate_space:display.coordinate_space,capture_atomic:false}},navigation:[],data_summary:'Explicit native backend contract double'},
    frame:{revision:'a'.repeat(64),display_id:'1',width:1280,height:720,bounds,mimeType:'image/jpeg',data:Buffer.from([255,216,255,217]).toString('base64')}}
  let reject=false,closed=0
  const desktop=new DesktopProxy(desktopPlatform(os),'/never-launched',{
    request:async(op,args)=>{calls.push([op,args]);if(op==='remote_targets')return [display];if(op==='remote_observe')return structuredClone(packet)
      if(op==='remote_act'){if(reject)throw new ComputerUseError('STALE_OBSERVATION','original native refusal');assert.equal(args.revision,packet.frame.revision)
        if(args.params.operation==='semantic')packet.state.interactive_elements[0].value=args.params.action.params.value
        packet.frame.revision='c'.repeat(64);return {dispatched:true,verified:false}}
      throw Error(`Unexpected native operation ${op}`)},close:async()=>{closed++}})
  const remote=new RemoteDesktopAdapter(desktop),runtime=new ComputerUseRuntime([desktop,remote],true),scripts=new ComputerScriptRunner(runtime)
  const server=createComputerUseServer(runtime,desktop),client=new Client({name:'remote-desktop-contract-smoke',version:'1'}),[ct,st]=InMemoryTransport.createLinkedPair()
  try {
    assert.equal(calls.length,0);assert.equal(runtime.capabilities().adapters[1].vm,false);assert.equal(calls.length,0)
    assert.deepEqual(await runtime.targets({adapter:'remote-desktop'}),{'remote-desktop':[display]})
    await server.connect(st);await client.connect(ct)
    const wire=await client.callTool({name:'computer_observe',arguments:{adapter:'remote-desktop',target:display.target}})
    assert.notEqual(wire.isError,true);assert.deepEqual(wire.content.map(p=>p.type),['text','image']);assert.equal(wire.content[1].data,packet.frame.data)
    const o=JSON.parse(wire.content[0].text);assert.equal(o.meta.coverage.complete_internal_state,false);assert.equal(o.environment.frame.bounds.x,-2560)
    assert.ok(!wire.content[0].text.includes(packet.frame.data));assert.ok(!JSON.stringify(wire.structuredContent).includes(packet.frame.data))
    assert.equal(o.interactive_elements[0].metadata.source,'accessibility');assert.equal(o.interactive_elements.at(-1).metadata.semantic_evidence,'pixels_only')
    const reads=calls.length;assert.equal((await runtime.inspect({observation_id:o.meta.observation_id,query:'Status'})).elements.length,1);assert.equal(calls.length,reads)
    const action={observation_id:o.meta.observation_id,action_type:'invoke_function',target:'remote:surface',params:{operation:'click',x:0,y:0}}
    for(const params of [{operation:'click',x:1280,y:0},{operation:'click',x:-1,y:0},{operation:'click',x:1.5,y:0},{operation:'click',x:0,y:0,script:'no'},{operation:'key',key:'enter',modifiers:['shift','shift']},{operation:'type_text',text:'\n'}]) {
      await assert.rejects(runtime.act({...action,params}),e=>e.code==='INVALID_ACTION');assert.ok(!calls.some(([op])=>op==='remote_act'))
    }
    // Reobserve because attempted actions consume their token only after validation.
    const fresh=await runtime.observe({adapter:'remote-desktop',target:display.target});const before=calls.filter(([op])=>op==='remote_observe').length
    const result=await runtime.act({...action,observation_id:fresh.meta.observation_id})
    assert.equal(result.execution,'executed');assert.equal(result.verification.status,'not_requested');assert.equal(calls.filter(([op])=>op==='remote_observe').length,before+1)
    assert.equal(calls.find(([op])=>op==='remote_act')[1].target,display.target)
    await assert.rejects(runtime.act({...action,observation_id:fresh.meta.observation_id}),e=>e.code==='STALE_OBSERVATION')
    const batch=await scripts.run({code:`const s=await computer.observe({adapter:'remote-desktop',target:'display:1'});await computer.act({observation_id:s.meta.observation_id,action_type:'set_value',target:'native:1',params:{value:'passed'},expect_observation:{target:'native:1',value:'passed'}});return (await computer.observe({adapter:'remote-desktop',target:'display:1'})).interactive_elements[0].value;`})
    assert.equal(batch.result,'passed');assert.equal(batch.images.length,3);assert.equal(batch.image_observations[0].adapter,'remote-desktop')
    reject=true;const refusal=await runtime.observe({adapter:'remote-desktop',target:display.target}),attempts=calls.filter(([op])=>op==='remote_act').length
    await assert.rejects(runtime.act({...action,observation_id:refusal.meta.observation_id}),e=>e.code==='STALE_OBSERVATION'&&e.message==='original native refusal');assert.equal(calls.filter(([op])=>op==='remote_act').length,attempts+1)
    packet.frame.display_id='other';await assert.rejects(remote.observe('display:1'),e=>e.code==='INVALID_FRAME');packet.frame.display_id='1'
    packet.state.environment.remote_desktop.displays.push(structuredClone(display));await assert.rejects(remote.observe('display:1'),e=>e.code==='INVALID_FRAME');packet.state.environment.remote_desktop.displays.pop()
    display.target='display:other';await assert.rejects(remote.targets(),e=>e.code==='INVALID_FRAME');display.target='display:1'
    display.coordinate_space=os==='darwin'?'screen_pixels':'screen_points';await assert.rejects(remote.targets(),e=>e.code==='INVALID_FRAME');display.coordinate_space=os==='darwin'?'screen_points':'screen_pixels'
    packet.frame.bounds={...bounds,x:0};await assert.rejects(remote.observe('display:1'),e=>e.code==='INVALID_FRAME');packet.frame.bounds=bounds
    packet.frame.data='malformed';await assert.rejects(remote.observe('display:1'),e=>e.code==='INVALID_FRAME');packet.frame.data=Buffer.from([255,216,255,217]).toString('base64')
    packet.state.interactive_elements[0].metadata.secure=true;await assert.rejects(remote.observe('display:1'),e=>e.code==='VISUAL_SECURE_CONTENT');packet.state.interactive_elements[0].metadata.secure=false
    const readonly=new ComputerUseRuntime([new RemoteDesktopAdapter(desktop)],false)
    try{const read=await readonly.observe({adapter:'remote-desktop',target:'display:1'});await assert.rejects(readonly.act({...action,observation_id:read.meta.observation_id}),e=>e.code==='READ_ONLY')}finally{await readonly.close()}
  }finally{scripts.close();await client.close();await server.close();await runtime.close()}
  assert.equal(closed,1)
}
console.log('PASS: real MCP image/ASIL + QuickJS loop, display/layout binding, negative-origin coordinates, one post-action capture, stale-token/no-retry/readonly/secure checks; macOS/Windows backends are contract doubles, no personal desktop capture/input')
