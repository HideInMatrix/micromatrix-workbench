// Adapted from ASIL softwaregen/{generator,qualification,validation}.py @ ca7706c, Apache-2.0.
// Reviewed plans first; no second Agent, model SDK, code generation or automatic deployment.
import type { Action } from "../protocol.js";
import { fail } from "../protocol.js";
import { onboardingProfileSchema, interfacePlanSchema, type OnboardingProfile, type ExtensionBundle } from "./models.js";
import { auditBundle } from "./audit.js";
import { canonicalSha256 } from "./templates.js";
import type { DeclarativeAdapter } from "./runtime.js";

export function qualifyProfile(input: unknown) {
  const profile = onboardingProfileSchema.parse(input), { evidence, runtime } = profile;
  const contains = (text: string, words: string[]) => words.some(word => text.toLowerCase().includes(word));
  const api = (words: string[]) => evidence.some(e => e.kind === "api_spec" && contains(e.locator, words))
    && !!runtime.allowed_hosts.length && !!(runtime.base_url || runtime.base_url_env);
  const commands = evidence.filter(e => e.kind === "command_help" || e.kind === "script");
  const command = (words: string[]) => !!runtime.allowed_executables.length && commands.some(e => contains(`${e.locator} ${e.excerpt}`, words));
  const files = evidence.filter(e => e.kind === "file_format" || e.kind === "sample_json");
  const jsonFile = files.some(e => e.kind === "sample_json" || e.sample !== null || /\.(json|ipynb)$/i.test(e.locator));
  const fileAction = files.some(e => contains(`${e.locator} ${e.excerpt}`, ["edit", "editable", "update", "mutate", "write"]));
  const observations = [api(["get ", "list", "read"]) && "http_json", command(["observe", "list", "get ", "read", "dump", "state"]) && "command_json", jsonFile && "json_file"].filter((s): s is string => !!s);
  const actions = [api(["post ", "put ", "patch ", "delete ", "create", "update"]) && "http_json", command(["set", "create", "update", "delete", "edit", "action", "operation", "accepts"]) && "command_json"].filter((s): s is string => !!s);
  const tier = observations.length && actions.length ? "direct_declarative" : files.length && fileAction ? "bridge_assisted" : "out_of_scope";
  return { software_id: profile.software_id, eligible: tier !== "out_of_scope", tier,
    available_observation_transports: tier === "bridge_assisted" ? ["command_json"] : observations,
    available_action_transports: tier === "bridge_assisted" ? ["command_json"] : actions,
    required_human_work: ["Interface evidence and runtime permissions", ...(tier === "bridge_assisted" ? ["Reviewed parser/converter or native bridge"] : []), "Task/evaluator acceptance", "GUI synchronization when required"],
    claim_boundary: "Evidence heuristics only, not runtime validation or complete application integration" };
}
export function assembleExtension(profileInput: unknown, planInput: unknown) {
  const profile: OnboardingProfile = onboardingProfileSchema.parse(profileInput), plan = interfacePlanSchema.parse(planInput);
  const bundle: ExtensionBundle = { schema_version: "1.0", profile, plan, provenance: { provider: "deterministic-ts", model: "reviewed-plan",
    profile_sha256: canonicalSha256(profile), plan_sha256: canonicalSha256(plan), prompt_sha256: "", api_calls: 0, elapsed_s: 0 } };
  const audit = auditBundle(bundle);
  const targets = [...new Set(plan.operations.map(o => o.target))];
  const example = (p: typeof plan.operations[number]["parameters"][number]) => p.enum.length ? p.enum[0]!
    : p.value_type === "string" ? `<${p.name}>` : p.value_type === "boolean" ? false : p.value_type === "object" ? {}
      : p.value_type === "array" ? [] : p.value_type === "integer" ? Math.ceil(p.minimum ?? Math.min(1, p.maximum ?? 1)) : p.minimum ?? Math.min(1, p.maximum ?? 1);
  const actionSchema = { software: profile.display_name, supported_action_types: [...new Set(plan.operations.map(o => o.action_type))],
    target: targets.length === 1 ? targets[0] : targets, description: plan.summary,
    actions: plan.operations.map(o => ({ name: o.name, description: o.description, evidence_refs: o.evidence_refs,
      params_schema: { operation: o.name, arguments: Object.fromEntries(o.parameters.map(p => [p.name, { type: p.value_type, required: p.required,
        ...(p.description ? {description:p.description} : {}), ...(p.enum.length ? {enum:p.enum} : {}), ...(p.minimum !== null ? {minimum:p.minimum} : {}), ...(p.maximum !== null ? {maximum:p.maximum} : {}) }])) },
      example: { action_type: o.action_type, target: o.target, params: { operation: o.name, arguments: Object.fromEntries(o.parameters.filter(p => p.required).map(p => [p.name, example(p)])) } } })),
    done_action: { description: "Report only after independent task acceptance; this is not a Computer Use executable operation", example: {action_type:"done",target:"",params:{}} }, limitations: plan.limitations };
  const report = { ok: audit.ok, audit, qualification: qualifyProfile(profile), bundle_sha256: canonicalSha256(bundle),
    ...bundle.provenance, hash_format: "sorted-json-js/1", observation_view_count: plan.observation_views.length, operation_count: plan.operations.length,
    note: "Candidate only. Review/pin artifacts and grant permissions separately. Python float serialization hashes are not JS canonical hashes." };
  return { bundle, actionSchema, report };
}
/** Isolated host probe, never an MCP approval bypass. Caller must explicitly opt into mutations. */
export async function probeExtension(adapter: DeclarativeAdapter, options: { action?: Action; allowActions?: boolean; signal?: AbortSignal } = {}) {
  if (options.action && !options.allowActions) fail("READ_ONLY", "Action probe requires explicit allowActions");
  const before = await adapter.observe(adapter.id); let action: Record<string, unknown> | null = null, after = before;
  if (options.action) {
    adapter.validateAction(before, options.action);
    await adapter.execute(adapter.id, before, options.action, options.signal);
    after = await adapter.observe(adapter.id);
    // No arguments/content in evidence output. Hash changes are not semantic task success.
    action = { validated: true, operation: options.action.params.operation, action_type: options.action.action_type,
      before_sha256: before.revision, after_sha256: after.revision, state_changed: before.revision !== after.revision };
  }
  return { ok: true, software_id: adapter.id, bundle_sha256: adapter.capabilities().bundle_sha256, hash_format: "sorted-json-js/1",
    observation: { sha256: after.revision, element_count: after.interactive_elements.length }, action,
    claim_boundary: "Host probe of mapped state; not GUI synchronization, independent evaluator acceptance or Docker validation" };
}
