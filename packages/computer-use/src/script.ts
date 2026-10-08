import { z } from "zod";
import { newQuickJSWASMModule, newVariant, RELEASE_SYNC, type QuickJSHandle } from "quickjs-emscripten";
import { ComputerUseError, fail, type Json } from "./protocol.js";
import { ComputerUseRuntime } from "./runtime.js";

declare const __MICROMATRIX_QUICKJS_WASM__: string | undefined;
const engine = () => newQuickJSWASMModule(typeof __MICROMATRIX_QUICKJS_WASM__ === "string"
  ? newVariant(RELEASE_SYNC,{wasmBinary:Uint8Array.from(Buffer.from(__MICROMATRIX_QUICKJS_WASM__,"base64")).buffer}) : RELEASE_SYNC);
let module:ReturnType<typeof engine>|undefined;
export const scriptInput=z.object({code:z.string().min(1).max(16_384),timeout_ms:z.number().int().min(100).max(60_000).default(30_000)}).strict();

/** QuickJS/WASM, not Node eval/vm. The only host crossing is bounded JSON RPC to existing approved tools. */
export class ComputerScriptRunner {
  #running=false; #closed=false; readonly #lifecycle=new AbortController();
  constructor(readonly runtime:ComputerUseRuntime) {}
  async run(input:unknown,signal?:AbortSignal) {
    const {code,timeout_ms}=scriptInput.parse(input);
    if(!this.runtime.allowActions) fail("READ_ONLY","Batch JavaScript requires enabled actions and MCP approval");
    if(this.#closed) fail("CLOSED","Script runner stopped");
    if(this.#running) fail("BUSY","One Computer Use batch at a time");
    signal=AbortSignal.any([this.#lifecycle.signal,AbortSignal.timeout(timeout_ms),...(signal?[signal]:[])]);
    signal.throwIfAborted();this.#running=true;
    let quickjs:Awaited<ReturnType<typeof engine>>;
    try {quickjs=await(module??=engine());} catch {module=undefined;this.#running=false;fail("SCRIPT_INITIALIZATION_FAILED","Cannot load embedded JavaScript engine");}
    const vm=quickjs.newContext(),wallDeadline=Date.now()+timeout_ms;
    const pending=new Set<Promise<void>>(), handles=new Set<{dispose():void}>();
    let queue=Promise.resolve(), calls=0, stopped:ComputerUseError|undefined, cpuDeadline=Date.now()+1000;
    const events:Record<string,Json>[]=[], images:{data:string;mimeType:"image/jpeg"}[]=[], imageObservations:Record<string,Json>[]=[];
    vm.runtime.setMemoryLimit(32*1024*1024);vm.runtime.setMaxStackSize(512*1024);
    vm.runtime.setInterruptHandler(()=>signal!.aborted||Date.now()>cpuDeadline||Date.now()>wallDeadline);
    const jsonHandle=(data:unknown):QuickJSHandle=>{
      const text=JSON.stringify(data??null);
      if(Buffer.byteLength(text)>1024*1024) fail("SCRIPT_OUTPUT_LIMIT","Host result exceeds 1 MiB");
      return vm.unwrapResult(vm.evalCode(`JSON.parse(${JSON.stringify(text)})`));
    };
    const pump=()=>{cpuDeadline=Date.now()+1000;const jobs=vm.runtime.executePendingJobs(100);
      if(jobs.error) {jobs.error.dispose();stopped??=new ComputerUseError("SCRIPT_INTERRUPTED","JavaScript failed or exceeded CPU limits");} };
    const api=vm.newObject();
    for(const method of ["capabilities","targets","observe","inspect","validate","act"] as const) {
      const fn=vm.newFunction(method,(argument)=>{
        if(stopped||signal!.aborted) return {error:vm.newError("Batch stopped")};
        if(++calls>32) {stopped=new ComputerUseError("SCRIPT_CALL_LIMIT","Maximum 32 host calls per batch");return {error:vm.newError(stopped.message)};}
        let args:unknown;
        try {args=argument?vm.dump(argument):{};const bytes=JSON.stringify(args??{});if(Buffer.byteLength(bytes)>65_536) throw new Error();args=JSON.parse(bytes);}
        catch {stopped=new ComputerUseError("INVALID_ARGUMENT","Host arguments must be bounded JSON");return {error:vm.newError(stopped.message)};}
        const deferred=vm.newPromise();handles.add(deferred);
        const task=queue.then(async()=>{
          if(stopped||signal!.aborted) throw stopped??new ComputerUseError("SCRIPT_CANCELLED","Batch cancelled; mutation outcome may be unknown");
          const result=method==="capabilities"?this.runtime.capabilities():method==="act"?await this.runtime.act(args,signal):await this.runtime[method](args);
          const observation=method==="observe"?result:method==="act"?(result as {observation:unknown}).observation:undefined;
          if(observation) {
            const meta=(observation as {meta:{observation_id:string;adapter:string;target:string}}).meta;
            const image=this.runtime.image(meta.observation_id);
            if(image) {
              if(images.length===3){images.shift();imageObservations.shift();}
              images.push(image);imageObservations.push({step:events.length+1,observation_id:meta.observation_id,adapter:meta.adapter,target:meta.target});
            }
          }
          events.push({step:events.length+1,method,status:"completed"});
          cpuDeadline=Date.now()+1000;const handle=jsonHandle(result);deferred.resolve(handle);handle.dispose();
        }).catch(error=>{
          stopped??=error instanceof ComputerUseError?error:new ComputerUseError("SCRIPT_HOST_FAILED","Host operation failed; no further batch actions executed");
          events.push({step:events.length+1,method,status:"failed_or_unknown",error:stopped.code});
          if(vm.alive) {const handle=vm.newError(stopped.message);deferred.reject(handle);handle.dispose();}
        }).finally(()=>{if(vm.alive)pump();pending.delete(task);});
        queue=task;pending.add(task);return deferred.handle;
      });
      vm.setProp(api,method,fn);fn.dispose();
    }
    vm.setProp(vm.global,"computer",api);api.dispose();
    // Playwright-style facade lives entirely inside QuickJS; it exposes no Page/Locator host objects.
    const facade=vm.evalCode(`globalThis.browser=Object.freeze({
      tabs:()=>computer.targets({adapter:"browser"}),
      page:(target)=>{
        const observe=(visual=false)=>computer.observe({adapter:"browser",target:visual?target.replace(/\\/visual$/,"")+"/visual":target.replace(/\\/visual$/,"")});
        const act=async(match,type,params)=>{const state=await observe();const nodes=state.interactive_elements.filter(n=>n.metadata?.secure!==true&&match(n));if(nodes.length!==1)throw Error("Locator must match exactly one observed element");return computer.act({observation_id:state.meta.observation_id,action_type:type,target:nodes[0].id,params});};
        const locator=(match)=>Object.freeze({click:()=>act(match,"invoke_function",{operation:"click"}),fill:(value)=>act(match,"set_value",{value}),selectOption:(value)=>act(n=>match(n)&&n.metadata?.tag==="select","set_value",{value}),press:(key)=>act(match,"invoke_function",{operation:"press",key}),scroll:(delta)=>act(match,"invoke_function",{operation:"scroll",delta})});
        return Object.freeze({observe,goto:(url)=>act(n=>n.id==="browser:page","navigate",{url}),
          getByRole:(role,options={})=>locator(n=>n.type===role&&(options.name===undefined||n.label===options.name)),
          getByText:(text)=>locator(n=>n.label===text),
          locator:(css)=>{if(typeof css!=="string"||!/^([a-z]+|#[A-Za-z_][A-Za-z0-9_-]*)$/.test(css))throw Error("Only simple tag or ID selectors; use getByRole for semantic targeting");return locator(n=>css.startsWith("#")?n.metadata?.dom_id===css.slice(1):n.metadata?.tag===css);}
        });
      }
    });`);
    if(facade.error){facade.error.dispose();vm.dispose();this.#running=false;fail("SCRIPT_INITIALIZATION_FAILED","Cannot initialize restricted browser facade");}facade.value.dispose();
    let resultHandle:QuickJSHandle|undefined;
    try {
      // No module loader, timers, network, filesystem, process, require or host objects.
      const evaluated=vm.evalCode(`(async()=>{"use strict";${code}\n})()`,"approved-computer-batch.js");
      if(evaluated.error) {evaluated.error.dispose();fail("SCRIPT_FAILED","JavaScript parse/execution failed or CPU/memory limit reached");}
      resultHandle=evaluated.value;
      while(true) {
        signal.throwIfAborted();if(stopped)throw stopped;
        pump();if(stopped)throw stopped;
        const state=vm.getPromiseState(resultHandle);
        if(state.type==="fulfilled") {
          const output=vm.dump(state.value);state.value.dispose();
          // Unawaited host calls are still drained in request order; never leave actions running after success.
          await queue;if(stopped)throw stopped;
          const bytes=JSON.stringify(output??null);if(Buffer.byteLength(bytes)>65_536) fail("SCRIPT_OUTPUT_LIMIT","Batch return value exceeds 64 KiB");
          return {status:"completed",calls,steps:events,result:JSON.parse(bytes) as Json,images,image_observations:imageObservations,
            note:"One approved script; host calls execute sequentially, fresh observations required. Completion is not independent task acceptance. No rollback or automatic retry."};
        }
        if(state.type==="rejected") {state.error.dispose();fail("SCRIPT_FAILED","JavaScript rejected; partial actions are not rolled back or retried");}
        await new Promise(resolve=>setTimeout(resolve,5));
      }
    } catch(error) {
      if(signal.aborted) stopped??=new ComputerUseError("SCRIPT_CANCELLED","Batch timed out/cancelled; partial actions may have occurred. Observe before retrying");
      stopped??=error instanceof ComputerUseError?error:new ComputerUseError("SCRIPT_FAILED","JavaScript batch failed");
      throw new ComputerUseError(stopped.code,stopped.message,{steps:events,automatic_retry:false,rollback:false});
    } finally {
      // Abort must stop dispatch even when the script did not await its pending calls.
      stopped??=new ComputerUseError("SCRIPT_ENDED","Batch ended");
      await Promise.all(pending);
      resultHandle?.dispose();for(const handle of handles)handle.dispose();vm.dispose();this.#running=false;
    }
  }
  close(){this.#closed=true;this.#lifecycle.abort();}
}
