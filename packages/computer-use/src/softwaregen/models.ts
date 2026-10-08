// Adapted from sharryXR/ASIL softwaregen/models.py @ ca7706c (Apache-2.0).
// Changes: TS/Zod contracts, bounded resources; no Python runtime. See third_party/asil.
import { z } from "zod";
import { actionType } from "../protocol.js";

const text = z.string().max(8192), nonempty = text.min(1);
const identifier = z.string().min(1).max(128).regex(/^[a-zA-Z][a-zA-Z0-9_.-]*$/);
const variable = z.string().min(1).max(128).regex(/^[a-zA-Z_][a-zA-Z0-9_]*$/);
const strings = z.array(text).max(128), refs = z.array(identifier).min(1).max(128);
const json = z.json(), dictionary = z.record(z.string().max(128), json);
export const runtimeBindingsSchema = z.object({
  base_url: text.default(""), base_url_env: z.union([z.literal(""), variable]).default(""),
  allowed_hosts: strings.default([]), allowed_executables: strings.default([]), filesystem_root: nonempty.default("."),
  headers: z.record(z.string().max(128), text).default({}), request_timeout_s: z.number().finite().gt(0).max(120).default(10),
}).strict();
export const onboardingProfileSchema = z.object({
  software_id: z.string().max(64).regex(/^[a-z][a-z0-9_]*$/), display_name: z.string().min(1).max(128), version: text.default(""),
  integration_pattern: z.enum(["file_backed", "native_script", "service_api", "hybrid"]), description: nonempty,
  evidence: z.array(z.object({ id: identifier, kind: z.enum(["api_spec", "command_help", "sample_json", "source_code", "script", "file_format"]),
    locator: nonempty, excerpt: nonempty, sample: json.nullable().default(null) }).strict()).min(1).max(128),
  runtime: runtimeBindingsSchema, requirements: strings.default([]), known_limitations: strings.default([]),
}).strict();
const argv = z.array(z.string().max(8192).refine(value => !value.includes("\0"))).min(1).max(64);
export const observationProbeSchema = z.discriminatedUnion("transport", [
  z.object({ transport: z.literal("http_json"), method: z.literal("GET").default("GET"), path: nonempty,
    query: dictionary.default({}), items_pointer: text.default(""), evidence_refs: refs }).strict(),
  z.object({ transport: z.literal("command_json"), argv, items_pointer: text.default(""), evidence_refs: refs }).strict(),
  z.object({ transport: z.literal("json_file"), path: nonempty, items_pointer: text.default(""), evidence_refs: refs }).strict(),
]);
export const parameterSpecSchema = z.object({
  name: variable, value_type: z.enum(["string", "integer", "number", "boolean", "object", "array"]), required: z.boolean().default(true),
  description: text.default(""), enum: z.array(json).max(128).default([]), minimum: z.number().finite().nullable().default(null), maximum: z.number().finite().nullable().default(null),
}).strict();
export const actionRequestSchema = z.discriminatedUnion("transport", [
  z.object({ transport: z.literal("http_json"), method: z.enum(["POST", "PUT", "PATCH", "DELETE"]), path: nonempty,
    query: dictionary.default({}), body: json.default({}) }).strict(),
  z.object({ transport: z.literal("command_json"), argv, stdin: json.nullable().default(null) }).strict(),
]);
export const interfacePlanSchema = z.object({
  summary: nonempty,
  observation_views: z.array(z.object({ id: identifier, description: nonempty, probe: observationProbeSchema,
    element: z.object({ id_prefix: text.default(""), id_pointer: nonempty, type: z.string().min(1).max(128), label_pointer: text.default(""),
      value_fields: z.record(z.string().max(128), text).default({}), metadata_fields: z.record(z.string().max(128), text).default({}),
      editable: z.boolean().default(true), actions: z.array(identifier).max(64).default([]), evidence_refs: refs }).strict(), evidence_refs: refs }).strict()).min(1).max(64),
  operations: z.array(z.object({ name: identifier, description: nonempty, action_type: actionType(), target: z.string().min(1).max(2048),
    parameters: z.array(parameterSpecSchema).max(64).default([]), request: actionRequestSchema, evidence_refs: refs }).strict()).min(1).max(64),
  limitations: strings.default([]),
}).strict();
const hash = z.string().regex(/^[0-9a-f]{64}$/);
export const extensionBundleSchema = z.object({
  schema_version: z.literal("1.0").default("1.0"), profile: onboardingProfileSchema, plan: interfacePlanSchema,
  provenance: z.object({ provider: nonempty, model: nonempty, profile_sha256: hash, plan_sha256: hash,
    prompt_sha256: z.union([z.literal(""), hash]).default(""), api_calls: z.number().int().min(0).default(0), elapsed_s: z.number().finite().min(0).default(0) }).strict(),
}).strict();
export type OnboardingProfile = z.infer<typeof onboardingProfileSchema>;
export type InterfacePlan = z.infer<typeof interfacePlanSchema>;
export type ExtensionBundle = z.infer<typeof extensionBundleSchema>;
export type ParameterSpec = z.infer<typeof parameterSpecSchema>;
export type OperationSpec = InterfacePlan["operations"][number];
export type ObservationProbe = z.infer<typeof observationProbeSchema>;
export interface AuditFinding { severity: "error" | "warning"; code: string; location: string; message: string }
export interface AuditReport { ok: boolean; error_count: number; warning_count: number; findings: AuditFinding[] }
