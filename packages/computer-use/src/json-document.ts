import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { open, realpath, readdir, rename, rm } from "node:fs/promises";
import path from "node:path";
import { exactParams, fail, type Action, type Adapter, type Element, type Json, type State } from "./protocol.js";

const LIMIT = 256 * 1024;
const secret = /password|secret|token|credential|api[_-]?key/i;
function pointerToken(value: string) { return value.replace(/~/g, "~0").replace(/\//g, "~1"); }
function elements(value: Json, pointer = "", result: Element[] = []): Element[] {
  if (result.length >= 200) return result;
  const name = pointer.split("/").at(-1) ?? "document", sensitive = secret.test(name);
  const container = value !== null && typeof value === "object";
  const children = container ? Object.keys(value).map(key => `${pointer}/${pointerToken(key)}`) : [];
  result.push({ id: `json:${pointer}`, type: container ? Array.isArray(value) ? "array" : "object" : typeof value, label: name,
    ...(sensitive ? {} : { value: container ? null : typeof value === "string" ? value.slice(0,2048) : value }),
    editable: !sensitive && !container, available_actions: !sensitive && !container ? ["modify_file"] : [], children: children.map(id => `json:${id}`) });
  if (container && !sensitive) for (const [key, child] of Object.entries(value)) elements(child as Json, `${pointer}/${pointerToken(key)}`, result);
  return result;
}
export class JsonDocumentAdapter implements Adapter {
  readonly id = "json" as const; readonly source = "file_parse";
  constructor(readonly workspace: string) {}
  capabilities() { return { available: true, scope: "Existing .json files in the selected workspace; closed-file state only", operations: ["modify_file"] }; }
  async #path(target: string): Promise<string> {
    const root = await realpath(this.workspace), candidate = await realpath(path.resolve(root, target));
    const relative = path.relative(root, candidate);
    if (!relative || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative) || relative.split(path.sep).some(part => part.startsWith("."))
      || !candidate.endsWith(".json") || secret.test(path.basename(candidate))) fail("OUT_OF_SCOPE", "Only non-hidden, non-credential .json files inside the selected workspace are allowed");
    return candidate;
  }
  async #read(target: string) {
    const file = await this.#path(target), handle = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size > LIMIT) fail("FILE_LIMIT", "JSON document must be a regular file <= 256 KiB");
      const bytes = Buffer.alloc(LIMIT + 1), { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
      if (bytesRead > LIMIT) fail("FILE_LIMIT", "JSON document exceeded its size limit");
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, bytesRead));
      return { file, info, data: JSON.parse(text) as Json, revision: createHash("sha256").update(text).digest("hex") };
    } finally { await handle.close(); }
  }
  async targets() { return (await readdir(this.workspace, { withFileTypes: true })).filter(entry => entry.isFile() && entry.name.endsWith(".json") && !entry.name.startsWith(".") && !secret.test(entry.name)).slice(0,100).map(entry => ({ target: entry.name, type: "json_document" })); }
  async observe(target: string): Promise<State> {
    const doc = await this.#read(target), nodes = elements(doc.data);
    const ids = new Set(nodes.map(node => node.id));
    for (const node of nodes) node.children = node.children.filter(id => ids.has(id));
    return { revision: doc.revision, app_state: { document: target, bytes: doc.info.size, synchronized_with_gui: false }, interactive_elements: nodes,
      environment: { max_bytes: LIMIT, redacts_named_secrets: true, truncated: nodes.length >= 200 }, navigation: [],
      data_summary: "File-backed semantic document state; no promise about unsaved edits in a GUI. Values may be truncated/redacted." };
  }
  validateAction(state: State, action: Action) {
    exactParams(action.params,["value"]);
    if (action.action_type !== "modify_file" || !Object.hasOwn(action.params,"value")
      || !state.interactive_elements.some(element => element.id === action.target && element.editable)) fail("INVALID_ACTION", "Use modify_file on an advertised editable JSON leaf with params.value");
  }
  async execute(target: string, state: State, action: Action, signal?: AbortSignal) {
    this.validateAction(state,action); signal?.throwIfAborted();
    const doc = await this.#read(target);
    if (doc.revision !== state.revision) fail("STALE_OBSERVATION", "Document changed; observe again");
    const tokens = action.target.slice(5).split("/").slice(1).map(token => token.replace(/~1/g,"/").replace(/~0/g,"~"));
    if (!tokens.length || tokens.some(token => ["__proto__","constructor","prototype"].includes(token))) fail("INVALID_ACTION", "Root/prototype mutation is not supported");
    let parent = doc.data as Record<string,Json>;
    for (const token of tokens.slice(0,-1)) {
      if (!parent || typeof parent !== "object" || !Object.hasOwn(parent,token)) fail("STALE_OBSERVATION", "JSON target disappeared");
      parent = parent[token] as Record<string,Json>;
    }
    const key = tokens.at(-1)!;
    if (!parent || typeof parent !== "object" || !Object.hasOwn(parent,key)) fail("STALE_OBSERVATION", "JSON target disappeared");
    parent[key] = action.params.value as Json;
    const text = JSON.stringify(doc.data,null,2)+"\n";
    if (Buffer.byteLength(text) > LIMIT) fail("FILE_LIMIT", "Result exceeds JSON document size limit");
    const temporary = path.join(path.dirname(doc.file),`.asil-${randomUUID()}.tmp`);
    try {
      const handle = await open(temporary,"wx",doc.info.mode & 0o777);
      try { await handle.writeFile(text); await handle.sync(); } finally { await handle.close(); }
      signal?.throwIfAborted();
      if (await this.#path(target) !== doc.file) fail("STALE_OBSERVATION", "Document path changed before replacement");
      if ((await this.#read(target)).revision !== doc.revision) fail("STALE_OBSERVATION", "Document changed before atomic replacement");
      await rename(temporary,doc.file);
      return await this.observe(target);
    } finally { await rm(temporary,{force:true}); }
  }
  async close() {}
}
