// Adapted from ASIL softwaregen/audit.py @ ca7706c, Apache-2.0.
// Adds pointer checks, Windows shell/path restrictions and template permission protection.
import { posix, win32 } from "node:path";
import { extensionBundleSchema, type AuditFinding, type AuditReport, type ExtensionBundle } from "./models.js";
import { placeholder, envPlaceholder, validPointer, walkStrings } from "./templates.js";

export const shellExecutable = /^(?:a?sh|bash|csh|dash|fish|ksh|tcsh|zsh|cmd|powershell|pwsh|wscript|cscript)(?:\.exe)?$/i;
export function executableName(value: string): string { return win32.basename(posix.basename(value)); }
export function safeHttpPath(value: string): boolean {
  if (!value.startsWith("/") || value.startsWith("//") || /[\\?#\x00-\x20]/.test(value)) return false;
  try {
    for (const segment of value.split("/")) {
      let decoded = segment;
      for (let n = 0; n < 4; n++) {
        if ([".", ".."].includes(decoded) || /[\/\\\x00-\x1f\x7f]/.test(decoded)) return false;
        if (!/%[0-9a-f]{2}/i.test(decoded)) break;
        decoded = decodeURIComponent(decoded);
      }
      if (/%[0-9a-f]{2}/i.test(decoded) || [".", ".."].includes(decoded) || /[\/\\\x00-\x1f\x7f]/.test(decoded)) return false;
    }
    return true;
  } catch { return false; }
}
export function safeFilePath(value: string): boolean {
  return !!value && !posix.isAbsolute(value) && !win32.isAbsolute(value) && !/[\\:\x00-\x1f?#]/.test(value)
    && !value.split("/").some(segment => segment === ".." || segment.startsWith(".")) && !value.includes("${");
}
export function auditBundle(input: unknown): AuditReport {
  const findings: AuditFinding[] = [], parsed = extensionBundleSchema.safeParse(input);
  const add = (code: string, location: string, message: string) => { findings.push({ severity: "error", code, location, message }); };
  if (!parsed.success) add("invalid_schema", "bundle", "Bundle does not satisfy bounded softwaregen 1.0 contracts");
  else audit(parsed.data, add);
  return { ok: findings.length === 0, error_count: findings.length, warning_count: 0, findings };
}
function audit(bundle: ExtensionBundle, add: (code: string, location: string, message: string) => void) {
  const { profile, plan } = bundle, runtime = profile.runtime;
  const duplicates = (ids: string[], location: string, code: string) => {
    const seen = new Set<string>(); for (const id of ids) { if (seen.has(id)) add(code, location, "Duplicate identifier"); seen.add(id); }
  };
  duplicates(profile.evidence.map(e => e.id), "profile.evidence", "duplicate_evidence");
  duplicates(plan.observation_views.map(v => v.id), "plan.observation_views", "duplicate_view");
  duplicates(plan.operations.map(o => o.name), "plan.operations", "duplicate_operation");
  const evidenceIds = new Set(profile.evidence.map(e => e.id)), operationIds = new Set(plan.operations.map(o => o.name));
  const references = (refs: string[], location: string) => { for (const ref of refs) if (!evidenceIds.has(ref)) add("unknown_evidence", location, "Evidence reference is absent from profile"); };
  const pointer = (value: string, location: string) => { if (!validPointer(value)) add("invalid_pointer", location, "Invalid RFC6901 pointer"); };
  const command = (args: string[], location: string) => {
    if (!runtime.allowed_executables.map(executableName).includes(executableName(args[0]!))) add("executable_not_allowed", location, "Executable not in profile allowlist");
    if (shellExecutable.test(executableName(args[0]!)) || /\.(?:bat|cmd|ps1)$/i.test(args[0]!)) add("shell_execution_forbidden", location, "Shell/script launchers forbidden");
    if (args[0]!.includes("${")) add("dynamic_executable", location, "Executable cannot be templated");
  };
  const http = (path: string, location: string) => {
    if (!runtime.base_url && !runtime.base_url_env) add("missing_base_url", location, "HTTP requires reviewed base URL binding");
    if (!safeHttpPath(path)) add("unsafe_http_path", location, "HTTP path must be a relative route without traversal, query or fragment");
  };
  if (runtime.base_url) {
    try {
      const url = new URL(runtime.base_url);
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.hash || url.search || !safeHttpPath(url.pathname)) throw new Error();
      if (!runtime.allowed_hosts.includes(url.hostname.replace(/^\[|\]$/g, ""))) add("host_not_allowed", "profile.runtime.base_url", "Host not approved");
    } catch { add("invalid_base_url", "profile.runtime.base_url", "Invalid credential-free HTTP(S) base URL"); }
  }
  for (const [key, value] of Object.entries(runtime.headers)) {
    const location = `profile.runtime.headers.${key}`;
    if (/^(host|content-length|transfer-encoding|connection|proxy-authorization|cookie)$/i.test(key)) add("controlled_header", location, "Transport/proxy/cookie header forbidden");
    if (/^(authorization|x-api-key|api-key)$/i.test(key) && !Array.from(value.matchAll(envPlaceholder)).length) add("literal_sensitive_header", location, "Authentication must use a private variable reference");
    if (value.replace(envPlaceholder, "").includes("${") || /[\r\n\0]/.test(value)) add("invalid_header", location, "Invalid header/template");
  }
  for (const [index, view] of plan.observation_views.entries()) {
    const location = `plan.observation_views[${index}]`;
    references(view.evidence_refs, location); references(view.probe.evidence_refs, `${location}.probe`); references(view.element.evidence_refs, `${location}.element`);
    pointer(view.probe.items_pointer, `${location}.probe.items_pointer`); pointer(view.element.id_pointer, `${location}.element.id_pointer`);
    pointer(view.element.label_pointer, `${location}.element.label_pointer`);
    for (const p of [...Object.values(view.element.value_fields), ...Object.values(view.element.metadata_fields)]) pointer(p, `${location}.element`);
    if (Object.keys(view.element.metadata_fields).some(key => ["secure", "operations", "view_id", "__proto__", "constructor", "prototype"].includes(key))) add("reserved_metadata", location, "Mapping cannot replace security/operation metadata");
    for (const name of view.element.actions) if (!operationIds.has(name)) add("unknown_element_action", location, "Element operation not declared");
    if (view.probe.transport === "http_json") http(view.probe.path, `${location}.probe.path`);
    if (view.probe.transport === "command_json") command(view.probe.argv, `${location}.probe.argv`);
    if (view.probe.transport === "json_file" && !safeFilePath(view.probe.path)) add("unsafe_file_path", location, "Only non-hidden relative JSON document paths supported");
    if (walkStrings(view.probe).some(value => value.includes("${"))) add("dynamic_probe", location, "Observation probe cannot contain action templates");
  }
  for (const [index, operation] of plan.operations.entries()) {
    const location = `plan.operations[${index}]`, request = operation.request;
    references(operation.evidence_refs, location); duplicates(operation.parameters.map(p => p.name), `${location}.parameters`, "duplicate_parameter");
    if (request.transport === "http_json") http(request.path, `${location}.request.path`);
    else command(request.argv, `${location}.request.argv`);
    const placeholders = new Set<string>();
    for (const text of walkStrings(request)) {
      for (const match of text.matchAll(placeholder)) placeholders.add(match[1]!);
      if (text.replace(placeholder, "").includes("${")) add("malformed_placeholder", `${location}.request`, "Malformed template");
    }
    const declared = new Set(operation.parameters.map(p => p.name));
    for (const name of placeholders) if (!declared.has(name)) add("unknown_placeholder", location, "Undeclared template parameter");
    for (const param of operation.parameters) {
      if (!placeholders.has(param.name)) add("unused_parameter", location, "Parameter not used in request");
      if (param.minimum !== null && param.maximum !== null && param.minimum > param.maximum) add("invalid_bounds", location, "Parameter minimum exceeds maximum");
    }
  }
}
