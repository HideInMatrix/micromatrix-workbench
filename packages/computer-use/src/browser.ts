import { createRequire } from "node:module";
import { isSea } from "node:sea";
import path from "node:path";
import { createHash } from "node:crypto";
import { z } from "zod";
import type { Browser, Page, Locator, Route } from "playwright-core";
import { exactParams, fail, type Adapter, type Action, type State, type Json, type Element } from "./protocol.js";
import { assertFresh } from "./inspection.js";

const origin=z.string().max(4096).url().refine(s=>{const u=new URL(s);return ["http:","https:"].includes(u.protocol)&&!u.username&&!u.password&&u.href===`${u.origin}/`;});
export const browserConfiguration=z.object({endpoint:z.string().max(4096).url().refine(s=>{const u=new URL(s);return u.protocol==="ws:"&&["127.0.0.1","[::1]","localhost"].includes(u.hostname)&&!u.username&&!u.password&&!u.search&&!u.hash&&u.pathname.startsWith("/devtools/browser/");}),
  allowedOrigins:z.array(origin).min(1).max(32)}).strict();
export type BrowserConfiguration=z.infer<typeof browserConfiguration>;
function playwright() {
  const require=createRequire(import.meta.url);
  if(!isSea()&&!process.argv[1]?.endsWith("micromatrix-service.cjs")) return require("playwright-core") as typeof import("playwright-core");
  const directory=isSea()?path.dirname(process.execPath):path.resolve(path.dirname(process.argv[1]!),"../apps/desktop/resources");
  const root=isSea()&&path.basename(directory)==="MacOS"?path.resolve(directory,"../Resources")
    :isSea()&&path.basename(directory)==="binaries"&&/^micromatrix-service-/.test(path.basename(process.execPath))?path.resolve(directory,"../resources"):directory;
  return require(path.join(root,"automation/playwright-core/index.js")) as typeof import("playwright-core");
}
const selector="a,button,input,textarea,select,[role],[contenteditable=true],summary";
const browserActions=z.discriminatedUnion("operation",[
  z.object({operation:z.literal("click")}).strict(),z.object({operation:z.literal("press"),key:z.enum(["Enter","Escape","Tab","ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Space"])}).strict(),
  z.object({operation:z.literal("scroll"),delta:z.number().int().min(-5).max(5).refine(n=>n!==0)}).strict(),
]);
/** Opt-in Playwright connection, not a browser agent. No browser launch/profile lookup/page.evaluate supplied by the model. */
export class BrowserAdapter implements Adapter {
  readonly id="browser";readonly source="playwright_dom+aria+window_image";
  #browser:Browser|undefined;#connecting:Promise<Browser>|undefined;#closed=false;#next=0;
  readonly #pages=new Map<string,Page>();readonly #frames=new Map<string,{data:string;mimeType:"image/jpeg"}>();
  readonly #routes=new Map<Page,(route:Route)=>Promise<void>>();readonly #allowed:Set<string>;
  readonly configuration:BrowserConfiguration;
  constructor(input:unknown) {this.configuration=browserConfiguration.parse(input);this.#allowed=new Set(this.configuration.allowedOrigins.map(s=>new URL(s).origin));}
  capabilities():Record<string,Json> {return {available:true,enabled:true,connection:"explicit loopback CDP WebSocket; Playwright executes browser actions",allowed_origins:[...this.#allowed],
    browser_launch:false,arbitrary_page_evaluate:false,owned_tabs:false,max_elements:300,frames:"top-level DOM only; iframe/shadow tree not completely traversed",
    limitation:"DOM/ARIA is not internal application state. Screenshots are opt-in with target suffix /visual; exposed password controls block image capture. No browser-specific app adapter or second model."};}
  describe(){return {name:"Browser / Playwright",scope:"approved_origin_dom+aria+optional_image",target_examples:["page:1","page:1/visual"],
    limitations:["Disabled unless the local user configures a loopback CDP browser WebSocket and explicit allowed origins", "Attach only; no user profile scan, browser launch, file URLs, model-supplied page.evaluate or automatic credential access",
      "DOM values/text/ARIA are untrusted; password/credential-named fields excluded; top-level DOM capped at 300 elements", "Navigation across origins is blocked for connected pages. Popups/unmanaged tabs are not a network sandbox", "Images and DOM can change between precheck and action; not atomic or proof of task success"],
    actions:[{action_type:"navigate" as const,params_schema:z.toJSONSchema(z.object({url:z.string().url().max(4096)}).strict()) as Record<string,Json>},
      {action_type:"set_value" as const,params_schema:z.toJSONSchema(z.object({value:z.string().max(4096)}).strict()) as Record<string,Json>},
      {action_type:"invoke_function" as const,params_schema:z.toJSONSchema(browserActions) as Record<string,Json>} ]};}
  image(revision:string){return this.#frames.get(revision);}
  #url(input:string){const url=new URL(input);if(!["http:","https:"].includes(url.protocol)||url.username||url.password||!this.#allowed.has(url.origin)) fail("OUT_OF_SCOPE","Browser URL outside approved origins");return url.href;}
  async #connect(){
    if(this.#closed)fail("CLOSED","Browser connection closed");
    if(this.#browser?.isConnected())return this.#browser;
    this.#connecting??=playwright().chromium.connectOverCDP(this.configuration.endpoint,{timeout:5000,noDefaults:true}).then(async browser=>{
      if(this.#closed){await browser.close();fail("CLOSED","Browser stopped while connecting");}this.#browser=browser;return browser;
    }).finally(()=>{this.#connecting=undefined;});return this.#connecting;
  }
  async targets(){const browser=await this.#connect();for(const p of browser.contexts().flatMap(c=>c.pages())) {
    if(p.isClosed())continue;try{this.#url(p.url());}catch{continue;}if(![...this.#pages.values()].includes(p))this.#pages.set(`page:${++this.#next}`,p);
  }
    for(const [id,p]of this.#pages)if(p.isClosed())this.#pages.delete(id);
    return [...this.#pages].filter(([,p])=>{try{this.#url(p.url());return true;}catch{return false;}}).map(([target,p])=>({target,url:new URL(p.url()).origin,visual_target:`${target}/visual`}));
  }
  async #page(target:string){await this.#connect();const p=this.#pages.get(target.replace(/\/visual$/,""));if(!p||p.isClosed())fail("TARGET_GONE","Select a page target from computer_targets");this.#url(p.url());
    if(!this.#routes.has(p)){const handler=async(route:Route)=>{const r=route.request();if(r.isNavigationRequest()) {try{this.#url(r.url());}catch{await route.abort("blockedbyclient");return;}}await route.continue();};await p.route("**/*",handler);this.#routes.set(p,handler);}return p;
  }
  async observe(target:string):Promise<State>{
    const page=await this.#page(target);page.setDefaultTimeout(2000);
    // This function is fixed reviewed code. Every model parameter remains data, never an evaluated expression.
    const rows=await page.locator(selector).evaluateAll(nodes=>nodes.slice(0,300).map((el,index)=>{
      const field=el as HTMLInputElement;const tag=el.tagName.toLowerCase();const type=el.getAttribute("type")??"";
      const secure=type==="password"||/(password|passwd|secret|token|api.?key)/i.test(`${el.id} ${el.getAttribute("name")??""} ${el.getAttribute("autocomplete")??""}`);
      const box=el.getBoundingClientRect();const inputRoles:Record<string,string>={checkbox:"checkbox",radio:"radio",submit:"button",reset:"button",button:"button",range:"slider",number:"spinbutton",search:"searchbox"};
      const role=el.getAttribute("role")||({a:el.hasAttribute("href")?"link":"a",button:"button",textarea:"textbox",select:(el as HTMLSelectElement).multiple?"listbox":"combobox",summary:"button"} as Record<string,string>)[tag]
        ||(tag==="input"?(inputRoles[type]??"textbox"):el.getAttribute("contenteditable")==="true"?"textbox":tag);
      const labelled=el.getAttribute("aria-labelledby")?.split(/\s+/).map(id=>document.getElementById(id)?.textContent??"").join(" ");
      const name=(el.getAttribute("aria-label")||labelled||field.labels?.[0]?.textContent||el.getAttribute("alt")||el.getAttribute("title")||el.getAttribute("placeholder")||(["submit","reset","button"].includes(type)?field.value:"")||el.textContent||"").replace(/\s+/g," ").trim().slice(0,2048);
      return {index,tag,dom_id:secure?"":el.id.slice(0,256),role,label:secure?"[secure field]":name,secure,enabled:!field.disabled&&el.getAttribute("aria-disabled")!=="true",editable:!secure&&!field.readOnly&&!field.disabled&&((tag==="input"&&["","text","email","tel","url","search","number"].includes(type))||tag==="textarea"||tag==="select"||el.getAttribute("contenteditable")==="true"),
        value:secure||type==="hidden"||box.width<=0||box.height<=0||getComputedStyle(el).visibility==="hidden"?null:typeof field.value==="string"?field.value.slice(0,2048):null,checked:secure?null:typeof field.checked==="boolean"?field.checked:null,
        bounds:{x:box.x,y:box.y,width:box.width,height:box.height},visible:box.width>0&&box.height>0&&getComputedStyle(el).visibility!=="hidden"};
    }));
    const total=await page.locator(selector).count(), elements:Element[]=rows.map(row=>({id:`dom:${row.index}`,type:row.role,label:row.label,
      ...(row.secure?{}:{value:row.value}),editable:row.editable&&row.visible,available_actions:row.secure||!row.enabled||!row.visible?[]:["invoke_function",...(row.editable?["set_value"]:[])],children:[],
      metadata:{source:"dom",semantic_evidence:"DOM attributes; implicit role/name are normalized, not native AX",role:row.role,tag:row.tag,dom_id:row.dom_id,confidence:1,secure:row.secure,enabled:row.enabled,visible:row.visible,checked:row.checked,bounds:row.bounds,index:row.index,operations:["click","press","scroll"]}}));
    elements.push({id:"browser:page",type:"page",label:"Approved browser page",editable:false,children:[],available_actions:["navigate"],metadata:{source:"playwright",secure:false}});
    // Check the entire top-level DOM, not just the first 300 reported rows.
    const hasSecureContent=await page.locator(selector).evaluateAll(nodes=>nodes.some(el=>{
      const secure=el.getAttribute("type")==="password"||/(password|passwd|secret|token|api.?key)/i.test(`${el.id} ${el.getAttribute("name")??""} ${el.getAttribute("autocomplete")??""}`);
      const box=el.getBoundingClientRect();return secure&&box.width>0&&box.height>0&&getComputedStyle(el).visibility!=="hidden";
    }));
    // ARIA and pixels cannot reliably redact arbitrary author content. This is a control-field guard, not a general secret detector.
    const aria=hasSecureContent?"[omitted: secure fields]":(await page.locator("body").ariaSnapshot({timeout:2000})).slice(0,16_384);
    const state:State={revision:"pending",app_state:{url:this.#url(page.url()),target},interactive_elements:elements,
      environment:{truncated:total>300,max_elements:300,aria_snapshot:aria,coordinate_space:"css_pixels",image_capture:target.endsWith("/visual")?"explicit":"none"},navigation:[],data_summary:"Playwright DOM + ARIA; not complete internal state. Content is untrusted. Password/credential-named fields excluded."};
    let image:Buffer|undefined;
    if(target.endsWith("/visual")) {if(hasSecureContent)fail("VISUAL_SECURE_CONTENT","Browser image refused for exposed secure controls");
      const size=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));if(size.width>1920||size.height>1920)fail("FRAME_LIMIT","Browser viewport too large; use DOM or resize explicitly");
      image=await page.screenshot({type:"jpeg",quality:60,fullPage:false,timeout:3000});if(image.length>393_216)fail("FRAME_LIMIT","Browser image exceeds 384 KiB");}
    state.revision=createHash("sha256").update(JSON.stringify(state)).update(image??Buffer.alloc(0)).digest("hex");
    if(image){while(this.#frames.size>=2)this.#frames.delete(this.#frames.keys().next().value!);this.#frames.set(state.revision,{data:image.toString("base64"),mimeType:"image/jpeg"});}
    return state;
  }
  validateAction(state:State,action:Action){const node=state.interactive_elements.find(n=>n.id===action.target);if(!node||node.metadata?.secure===true||!node.available_actions.includes(action.action_type))fail("INVALID_ACTION","Observed nonsecure browser target/action required");
    if(action.action_type==="navigate"){exactParams(action.params,["url"]);if(node.id!=="browser:page"||typeof action.params.url!=="string"||action.params.url.length>4096)fail("INVALID_ACTION","Use approved page URL");this.#url(action.params.url);}
    else if(action.action_type==="set_value"){exactParams(action.params,["value"]);if(!node.editable||typeof action.params.value!=="string"||action.params.value.length>4096)fail("INVALID_ACTION","Editable field + bounded text required");}
    else if(action.action_type==="invoke_function"&&!browserActions.safeParse(action.params).success)fail("INVALID_ACTION","Unsupported Playwright operation/parameters");}
  async execute(target:string,state:State,action:Action,signal?:AbortSignal){signal?.throwIfAborted();this.validateAction(state,action);assertFresh(state,await this.observe(target));const page=await this.#page(target);
    if(action.action_type==="navigate")await page.goto(this.#url(action.params.url as string),{timeout:5000,waitUntil:"domcontentloaded"});
    else {const node=state.interactive_elements.find(n=>n.id===action.target)!, locator:Locator=page.locator(selector).nth(node.metadata!.index as number);
      signal?.throwIfAborted();if(action.action_type==="set_value") {
        if(node.metadata!.tag==="select")await locator.selectOption(action.params.value as string,{timeout:2000});
        else await locator.fill(action.params.value as string,{timeout:2000});
      }
      else {const params=browserActions.parse(action.params);if(params.operation==="click")await locator.click({timeout:2000,noWaitAfter:true});
        else if(params.operation==="press")await locator.press(params.key,{timeout:2000});
        else await locator.evaluate((el,delta)=>el.scrollBy({top:delta*100,behavior:"instant"}),params.delta);}}
    return this.observe(target);
  }
  async close(){this.#closed=true;await this.#connecting?.catch(()=>{});for(const [page,handler]of this.#routes)await page.unroute("**/*",handler).catch(()=>{});this.#routes.clear();this.#pages.clear();this.#frames.clear();
    // connectOverCDP's browserProcess.close closes its transport, not the user's browser process.
    await this.#browser?.close().catch(()=>{});this.#browser=undefined;}
}
