// Adapted from ASIL softwaregen/runtime.py @ ca7706c, Apache-2.0.
// Changes: explicit host grants, bounded asynchronous transports, Pi/MCP state mapping and cancellation.
import { isDeepStrictEqual } from "node:util";
import { z } from "zod";
import { exactParams, fail, type Adapter, type Action, type Json, type State, type Element, type ProviderDescription } from "../protocol.js";
import { checkedState } from "../providers.js";
import { assertFresh } from "../inspection.js";
import { extensionBundleSchema, type ExtensionBundle, type OperationSpec, type ParameterSpec } from "./models.js";
import { auditBundle, executableName, safeHttpPath } from "./audit.js";
import { approveBindings, verifyIntegrity, type ApprovedBindings, type RuntimePermissions, type PrivateBindings } from "./bindings.js";
import { HttpJsonChannel, CommandJsonChannel, readScopedJson, MAX_BYTES } from "./io.js";
import { canonicalSha256, renderTemplate, renderPathTemplate, resolveJsonPointer } from "./templates.js";

const namedSecret = /password|secret|token|credential|api[_-]?key|authorization|cookie/i;
function privatePointer(pointer: string): boolean { return pointer.split("/").slice(1).some(token => namedSecret.test(token.replace(/~1/g,"/").replace(/~0/g,"~"))); }

function parameterSchema(parameter: ParameterSpec): z.ZodType<Json> {
  let schema: z.ZodType<Json>;
  switch (parameter.value_type) {
    case "string": schema = z.string().max(64 * 1024); break;
    case "integer": schema = z.number().int().safe(); break;
    case "number": schema = z.number().finite(); break;
    case "boolean": schema = z.boolean(); break;
    case "object": schema = z.record(z.string(), z.json()); break;
    case "array": schema = z.array(z.json()); break;
  }
  return schema;
}
export function validateArguments(operation: OperationSpec, input: Json): Record<string, Json> {
  if (!input || Array.isArray(input) || typeof input !== "object" || Buffer.byteLength(JSON.stringify(input)) > MAX_BYTES) fail("INVALID_ACTION", "Arguments must be a bounded JSON object");
  if (Object.keys(input).some(key => !operation.parameters.some(p => p.name === key))) fail("INVALID_ACTION", "Unknown semantic argument");
  for (const param of operation.parameters) {
    if (!Object.hasOwn(input, param.name)) { if (param.required) fail("INVALID_ACTION", "Required semantic argument missing"); continue; }
    const value = input[param.name]!;
    if (!parameterSchema(param).safeParse(value).success || param.enum.length && !param.enum.some(item => isDeepStrictEqual(item, value))
      || typeof value === "number" && (param.minimum !== null && value < param.minimum || param.maximum !== null && value > param.maximum)) fail("INVALID_ACTION", "Semantic argument violates type/enum/bounds");
  }
  return input;
}
function operationParamsSchema(operation: OperationSpec): Record<string, Json> {
  const properties = Object.fromEntries(operation.parameters.map(p => [p.name, { type: p.value_type, description: p.description,
    ...(p.enum.length ? { enum: p.enum } : {}), ...(p.minimum !== null ? { minimum: p.minimum } : {}), ...(p.maximum !== null ? { maximum: p.maximum } : {}) }]));
  return { type: "object", additionalProperties: false, required: ["operation", "arguments"], properties: {
    operation: { const: operation.name }, arguments: { type: "object", additionalProperties: false, properties, required: operation.parameters.filter(p => p.required).map(p => p.name) } } };
}
/** No model/eval: interprets audited profile+plan data. Created only with separate host-approved bindings. */
export class DeclarativeAdapter implements Adapter {
  readonly id: string; readonly source = "asil_declarative";
  readonly #bundle: ExtensionBundle; readonly #bindings: ApprovedBindings;
  readonly #command: CommandJsonChannel; readonly #http: HttpJsonChannel | undefined;
  #closed = false;
  private constructor(bundle: ExtensionBundle, bindings: ApprovedBindings) {
    this.#bundle = structuredClone(bundle); this.#bindings = bindings; this.id = bundle.profile.software_id;
    const timeout = Math.ceil(bundle.profile.runtime.request_timeout_s * 1000);
    this.#command = new CommandJsonChannel(bindings.root, timeout, bindings.commandEnvironment);
    this.#http = bindings.baseUrl ? new HttpJsonChannel(bindings.baseUrl, bindings.headers, timeout) : undefined;
  }
  static async create(input: unknown, permissions: RuntimePermissions, privateBindings: PrivateBindings = {}): Promise<DeclarativeAdapter> {
    const bundle = extensionBundleSchema.parse(input), report = auditBundle(bundle);
    if (!report.ok) fail("AUDIT_FAILED", `Extension audit failed: ${[...new Set(report.findings.map(f => f.code))].join(", ")}`);
    return new DeclarativeAdapter(bundle, await approveBindings(bundle, permissions, privateBindings));
  }
  describe(): ProviderDescription {
    const { profile, plan } = this.#bundle, types = [...new Set(plan.operations.map(o => o.action_type))];
    return { name: profile.display_name, scope: "reviewed_software_objects", target_examples: [profile.software_id],
      limitations: ["Approved open interfaces only; not complete UI/unsaved state or an OS sandbox", "Freshness is a precheck, not atomic compare-and-swap; execution may race external writers", ...profile.known_limitations, ...plan.limitations]
        .filter(Boolean).map(text => text.slice(0,2048)).slice(0, 20),
      actions: types.map(action_type => ({ action_type, params_schema: { anyOf: plan.operations.filter(o => o.action_type === action_type).map(operationParamsSchema) } })),
      operation_targets: plan.operations.map(operation => ({ target: operation.target, action_type: operation.action_type, operations: [operation.name] })) };
  }
  capabilities() { return { available: !this.#closed, schema_version: "1.0", protocol_mapping: "softwaregen-to-micromatrix-asil/1",
    bundle_sha256: canonicalSha256(this.#bundle), hash_format: "sorted-json-js/1",
    access_paths: [...new Set(this.#bundle.plan.observation_views.map(v => v.probe.transport))], atomic_preconditions: false,
    operations: this.#bundle.plan.operations.map(o => ({ name: o.name, target: o.target, action_type: o.action_type })) }; }
  async targets(): Promise<Json[]> { return [{ target: this.id, type: "reviewed_software", label: this.#bundle.profile.display_name }]; }
  #target(target: string) { if (this.#closed) fail("CLOSED", "Declarative provider closed"); if (target !== this.id) fail("OUT_OF_SCOPE", "Software target not installed"); }
  async #runCommand(argv: Json, stdin: Json | null, signal?: AbortSignal): Promise<Json> {
    if (!Array.isArray(argv) || argv.some(a => typeof a !== "string")) fail("INVALID_ACTION", "Rendered argv must contain only strings");
    const args = argv as string[], name = executableName(args[0]!);
    const executable = this.#bindings.executablePaths[name], binding = this.#bindings.permissions.executables[name];
    if (!executable || !binding || !binding.prefix.every((arg, i) => args[i + 1] === arg)) fail("INVALID_ACTION", "Command differs from approved executable/prefix");
    await verifyIntegrity(this.#bindings); signal?.throwIfAborted();
    return this.#command.request(executable, args.slice(1), stdin, signal);
  }
  async observe(target: string): Promise<State> { return this.#observe(target); }
  async #observe(target: string, signal?: AbortSignal): Promise<State> {
    this.#target(target);
    const elements: Element[] = [], raw: Json[] = [], counts: string[] = [], sources: string[] = [];
    for (const view of this.#bundle.plan.observation_views) {
      signal?.throwIfAborted(); const probe = view.probe; let payload: Json;
      if (probe.transport === "http_json") { payload = await this.#http!.request("GET", probe.path, probe.query, undefined, signal); sources.push("rest_api"); }
      else if (probe.transport === "command_json") { payload = await this.#runCommand(probe.argv, null, signal); sources.push("script_api"); }
      else { payload = await readScopedJson(this.#bindings.root, probe.path); sources.push("file_parse"); }
      raw.push(payload); if (Buffer.byteLength(JSON.stringify(raw)) > MAX_BYTES) fail("STATE_LIMIT", "Combined probe data exceeds 1 MiB");
      const selected = resolveJsonPointer(payload, probe.items_pointer), items = Array.isArray(selected) ? selected : [selected];
      if (items.length + elements.length > 2000) fail("STATE_LIMIT", "Probe data exceeds 2000 objects");
      counts.push(`${view.id}=${items.length}`);
      for (const item of items) {
        if (privatePointer(view.element.id_pointer)) fail("INVALID_STATE", "Private fields cannot provide public object identities");
        const id = resolveJsonPointer(item, view.element.id_pointer);
        if (id === null || typeof id === "object" || String(id) === "") fail("INVALID_STATE", "Expected stable scalar object ID");
        const label = view.element.label_pointer ? privatePointer(view.element.label_pointer) ? "[redacted]" : resolveJsonPointer(item, view.element.label_pointer) : id;
        const fields = (mapping: Record<string, string>) => Object.fromEntries(Object.entries(mapping).map(([key, pointer]) => [key, privatePointer(pointer) ? "[redacted]" : resolveJsonPointer(item, pointer)]));
        const names = view.element.actions;
        if (this.#redact(String(id)) !== String(id)) fail("INVALID_STATE", "Stable ID contains private runtime material");
        elements.push({ id: `${view.element.id_prefix}${id}`, type: view.element.type, label: this.#redact(String(label)) as string, value: this.#redact(fields(view.element.value_fields)),
          editable: view.element.editable, available_actions: [...new Set(names.map(name => this.#bundle.plan.operations.find(o => o.name === name)!.action_type))],
          children: [], data_type: "object", constraints: {}, metadata: { ...this.#redact(fields(view.element.metadata_fields)) as Record<string, Json>, view_id: view.id, operations: names } });
      }
    }
    return checkedState({ revision: canonicalSha256(raw), app_state: { current_view: this.#bundle.plan.observation_views[0]!.id, synchronized_with_gui: false },
      interactive_elements: elements, environment: { truncated: false, observation_sources: [...new Set(sources)], atomic_preconditions: false, max_bytes: MAX_BYTES },
      navigation: this.#bundle.plan.observation_views.map(view => ({ id: view.id, label: view.id, description: view.description })),
      data_summary: `${this.#bundle.profile.display_name}: ${elements.length} elements (${counts.join(", ")})` });
  }
  #redact(value: Json): Json {
    const secrets = [...Object.entries(this.#bindings.environment).filter(([key]) => key !== this.#bundle.profile.runtime.base_url_env).map(([,value]) => value),
      ...Object.entries(this.#bindings.commandEnvironment).filter(([key]) => !["SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"].includes(key.toUpperCase())).map(([,value]) => value),
      ...Object.values(this.#bindings.headers)].filter(v => v.length > 0);
    const clean = (item: Json): Json => {
      if (typeof item === "string") return secrets.reduce((text, secret) => text.split(secret).join("[redacted]"), item);
      if (Array.isArray(item)) return item.map(clean);
      if (item && typeof item === "object") return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, namedSecret.test(key) ? "[redacted]" : clean(child)]));
      return item;
    };
    return clean(value);
  }
  #operation(action: Action): { operation: OperationSpec; args: Record<string, Json> } {
    exactParams(action.params, ["operation", "arguments"]);
    const operation = this.#bundle.plan.operations.find(o => o.name === action.params.operation);
    if (!operation || operation.target !== action.target || operation.action_type !== action.action_type) fail("INVALID_ACTION", "Semantic operation/type/software target not declared");
    const args = validateArguments(operation, action.params.arguments ?? {});
    // Validate rendered transports during validation too, without issuing requests.
    if (operation.request.transport === "http_json" && !safeHttpPath(renderPathTemplate(operation.request.path, args))) fail("INVALID_ACTION", "Unsafe rendered HTTP route");
    renderTemplate(operation.request as unknown as Json, args);
    return { operation, args };
  }
  validateAction(_state: State, action: Action) { this.#operation(action); }
  async execute(target: string, state: State, action: Action, signal?: AbortSignal): Promise<State> {
    this.#target(target); const { operation, args } = this.#operation(action); signal?.throwIfAborted();
    assertFresh(state, await this.#observe(target, signal)); signal?.throwIfAborted();
    const request = operation.request;
    if (request.transport === "http_json") await this.#http!.request(request.method, renderPathTemplate(request.path, args),
      renderTemplate(request.query, args) as Record<string, Json>, renderTemplate(request.body, args), signal);
    else await this.#runCommand(renderTemplate(request.argv, args), renderTemplate(request.stdin, args), signal);
    return this.#observe(target, signal); // Independent read, not the mutation response.
  }
  async close() { this.#closed = true; this.#http?.close(); await this.#command.close(); }
}
