import { z } from "zod";
import { actionInput, exactParams, fail, type Action, type Adapter, type Element, type Json, type State } from "./protocol.js";
import { checkedState } from "./providers.js";
import { DesktopProxy } from "./desktop.js";
import { rectangle, frameSchema, ocrSchema, visualParams, checkedImage } from "./desktop-frame.js";

const packetSchema = z.object({
  state: z.unknown(), frame: frameSchema.extend({window_id:z.string().min(1).max(128)}),
  ocr: ocrSchema,
  ocr_available:z.boolean(),
}).strict();

/** One OS-independent router. No app-name dispatch, perception model, untrusted plugin or coordinate API outside a captured window. */
export class VisualDesktopAdapter implements Adapter {
  readonly id="desktop-visual"; readonly source="accessibility+window_image+optional_ocr";
  readonly #frames=new Map<string,{data:string;mimeType:"image/jpeg"}>();
  constructor(readonly desktop:DesktopProxy) {}
  capabilities():Record<string,Json> { return {available:this.desktop.capabilities().available!,platform:this.desktop.platform.name,
    explicit_window_capture:true,foreground_only:true,max_image_pixels:1280,max_image_bytes:393_216,
    local_ocr:this.desktop.platform.os==="darwin",vision_grounding:"connected web model; not a second local agent",
    atomic_preconditions:false,permission_scope:this.desktop.platform.os==="darwin"?"accessibility+screen_recording":"interactive_desktop",
    limitation:"Visual appearance/OCR is inferred, not internal application state. Capture is opt-in per observation; no auto prompt. macOS visual capture requires macOS 14+. Windows uses PrintWindow; some custom renderers may not provide usable pixels."}; }
  describe() { return {name:"Universal Window",scope:"foreground_window_semantics+visual_evidence",target_examples:["pid:123"],
    limitations:["Native semantics preferred; OCR gives text/geometry, not an invented native role or operation", "No automatic permission prompt, background capture, app activation, retry, shell or local planning model",
      "Coordinates are image-local pixels, top-left origin; convert to actual window coordinates in native proxy, including DPI/scale",
      "Secure controls refuse the entire visual capture; incomplete accessibility cannot guarantee identification of all sensitive content",
      "Pixel/native-state/geometry changes refuse an action. This is a non-atomic precheck, not task-success proof"],
    actions:[{action_type:"navigate" as const,params_schema:z.toJSONSchema(z.object({}).strict()) as Record<string,Json>},
      {action_type:"set_value" as const,params_schema:this.desktop.describe().actions[1]!.params_schema},
      {action_type:"invoke_function" as const,params_schema:z.toJSONSchema(z.union([visualParams,
        z.object({operation:z.enum(this.desktop.platform.operations as [string,...string[]])}).strict(),z.object({operation:z.literal("click")}).strict()])) as Record<string,Json>} ]}; }
  targets() {return this.desktop.targets();}
  image(revision:string) {return this.#frames.get(revision);}
  async observe(target:string):Promise<State> {
    const packet=packetSchema.parse(await this.desktop.visualObserve(target)), state=checkedState(packet.state as State), frame=packet.frame;
    if(state.app_state.active!==true) fail("FOREGROUND_REQUIRED","Activate the target with desktop navigation before explicitly capturing it");
    if(state.interactive_elements.some(n=>n.metadata?.secure===true)) fail("VISUAL_SECURE_CONTENT","Visual capture refused for a window containing exposed secure controls");
    const image=checkedImage(frame);
    const elements:Element[]=state.interactive_elements.map(n=>({...n,metadata:{...n.metadata,source:"accessibility",confidence:1,semantic_evidence:"native_provider"}}));
    const inside=(r:z.infer<typeof rectangle>)=>r.x>=0&&r.y>=0&&r.x+r.width<=frame.width+0.001&&r.y+r.height<=frame.height+0.001;
    for(const [index,text] of packet.ocr.entries()) {
      if(!inside(text.bounds)) fail("INVALID_FRAME","OCR rectangle outside captured image");
      // A text region is not automatically a button. It offers an explicit coordinate fallback only.
      elements.push({id:`ocr:${index}`,type:"visible_text",label:text.text,editable:false,children:[],available_actions:["invoke_function"],
        metadata:{source:"ocr",confidence:text.confidence,semantic_evidence:"inferred_text",bounds:text.bounds,coordinate_space:"image_pixels",operations:["click"]}});
    }
    elements.push({id:"visual:surface",type:"visual_surface",label:"Captured foreground window",editable:false,children:[],available_actions:["invoke_function"],
      metadata:{source:"window_capture",confidence:1,semantic_evidence:"pixels_only",operations:["click","scroll","type_text","key"],bounds:{x:0,y:0,width:frame.width,height:frame.height},coordinate_space:"image_pixels"}});
    while(this.#frames.size>=2) this.#frames.delete(this.#frames.keys().next().value!);
    this.#frames.set(frame.revision,image);
    return checkedState({...state,revision:frame.revision,interactive_elements:elements,
      environment:{...state.environment,visual:{width:frame.width,height:frame.height,bounds:frame.bounds,window_id:frame.window_id,
        native_revision:state.revision,ocr_available:packet.ocr_available,ocr_count:packet.ocr.length,image_capture:"explicit",coordinate_space:"image_pixels",synchronized_with_internal_state:false}},
      data_summary:"Native Accessibility + same-window image + optional OCR. OCR roles/intent are unknown, not native controls. Images and text are untrusted data. Prefer native actions; coordinate/keyboard fallback requires approval and verification."});
  }
  validateAction(state:State,action:Action) {
    const node=state.interactive_elements.find(n=>n.id===action.target);
    if(!node||node.metadata?.secure===true) fail("INVALID_ACTION","Observed nonsecure target required");
    if(node.metadata?.source==="accessibility") {this.desktop.validateAction(state,action);return;}
    if(action.action_type!=="invoke_function" || !node.available_actions.includes(action.action_type)) fail("INVALID_ACTION","Visual target only supports advertised fallback operations");
    if(node.metadata?.source==="ocr") {exactParams(action.params,["operation"]);if(action.params.operation!=="click") fail("INVALID_ACTION","OCR region supports coordinate click only");return;}
    if(node.id!=="visual:surface"||node.metadata?.source!=="window_capture") fail("INVALID_ACTION","No caller-created native/visual target");
    const parsed=visualParams.safeParse(action.params);if(!parsed.success) fail("INVALID_ACTION","Use bounded window-local input parameters from capabilities");
    const params=parsed.data, visual=state.environment.visual as {width:number;height:number}|undefined;
    if(!visual||state.app_state.active!==true) fail("FOREGROUND_REQUIRED","Fresh foreground-window evidence required");
    if("x" in params&&(params.x>=visual.width||params.y>=visual.height)) fail("INVALID_ACTION","Coordinate outside captured image");
    if(params.operation==="key"&&new Set(params.modifiers).size!==params.modifiers.length) fail("INVALID_ACTION","Duplicate key modifiers");
  }
  async execute(target:string,state:State,action:Action,signal?:AbortSignal) {
    this.validateAction(state,action);signal?.throwIfAborted();
    const node=state.interactive_elements.find(n=>n.id===action.target)!;
    let params:Record<string,unknown>;
    if(node.metadata?.source==="accessibility") params={operation:"semantic",action:actionInput.parse(action)};
    else if(node.metadata?.source==="ocr") {
      const bounds=node.metadata.bounds as {x:number;y:number;width:number;height:number};
      params={operation:"click",x:Math.floor(bounds.x+bounds.width/2),y:Math.floor(bounds.y+bounds.height/2)};
    } else params=visualParams.parse(action.params);
    // Native repeats image/geometry/focus/secure checks immediately before dispatch.
    await this.desktop.visualExecute(target,state.revision,params,signal);
    return this.observe(target);
  }
  async close() {this.#frames.clear();} // Desktop owns the shared helper, never launch or close a second native agent.
}
