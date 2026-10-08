import { z } from "zod";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Element {
  id: string; type: string; label: string; value?: Json; editable: boolean;
  available_actions: string[]; children: string[]; metadata?: Record<string, Json>;
  data_type?: string; constraints?: Record<string, Json>;
}
export interface State {
  revision: string; app_state: Record<string, Json>; interactive_elements: Element[];
  environment: Record<string, Json>; navigation: Json[]; data_summary: string;
}
export const stateInput = z.object({
  revision: z.string().min(1).max(512), app_state: z.record(z.string(), z.json()),
  interactive_elements: z.array(z.object({
    id: z.string().min(1).max(2048), type: z.string().max(128), label: z.string().max(16_384), value: z.json().optional(),
    editable: z.boolean(), available_actions: z.array(actionType()).max(6), children: z.array(z.string().min(1).max(2048)).max(2000),
    metadata: z.record(z.string(), z.json()).optional(),
    data_type: z.string().max(128).optional(), constraints: z.record(z.string(), z.json()).optional(),
  }).strict()).max(2000),
  environment: z.record(z.string(), z.json()), navigation: z.array(z.json()).max(2000), data_summary: z.string().max(8192),
}).strict();
export function actionType() { return z.enum(["navigate", "invoke_function", "set_value", "modify_file", "api_call", "batch"]); }
export interface Observation extends State {
  meta: { protocol: "micromatrix-asil/1"; adapter: string; source: string; target: string; observation_id: string; observed_at: string; expires_at: string; untrusted_content: true;
    coverage: { scope: string; complete_internal_state: false; truncated: boolean | null; element_count: number } };
}
export const providerId = z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/);
export const observationInput = z.object({ adapter: providerId, target: z.string().min(1).max(2048) }).strict();
export const targetsInput = z.object({ adapter: providerId.optional() }).strict();
/** Inspect an existing observation without recapture, helper launch or token invalidation. */
export const inspectInput = z.object({
  observation_id: z.string().uuid(), root: z.string().min(1).max(2048).optional(),
  query: z.string().min(1).max(256).optional(), type: z.string().min(1).max(128).optional(),
  actionable: z.boolean().optional(), editable: z.boolean().optional(),
  offset: z.number().int().min(0).max(2000).default(0), limit: z.number().int().min(1).max(100).default(50),
}).strict();
export const actionInput = z.object({
  observation_id: z.string().uuid(), action_type: actionType(),
  target: z.string().min(1).max(2048), params: z.record(z.string(), z.json()),
  expect_observation: z.union([
    z.boolean(), // Upstream flag; this product always recaptures after an action.
    z.object({ target: z.string().min(1).max(2048), value: z.json(), property: z.enum(["value", "label", "type", "editable"]).optional() }).strict(),
    z.object({ target: z.string().min(1).max(2048), value: z.json(), property: z.literal("metadata"), key: z.string().min(1).max(128) }).strict(),
  ]).optional(),
}).strict();
export type Action = z.infer<typeof actionInput>;
export const providerDescription = z.object({
  name: z.string().min(1).max(128), scope: z.string().min(1).max(128),
  target_examples: z.array(z.string().min(1).max(2048)).max(10),
  limitations: z.array(z.string().min(1).max(2048)).min(1).max(20),
  actions: z.array(z.object({ action_type: actionInput.shape.action_type, params_schema: z.record(z.string(), z.json()) }).strict()).max(6),
  // Reviewed software-level operations (including creation), not synthetic UI elements.
  operation_targets: z.array(z.object({ target: z.string().min(1).max(2048), action_type: actionType(),
    operations: z.array(z.string().min(1).max(128)).min(1).max(64) }).strict()).max(64).optional(),
}).strict();
export type ProviderDescription = z.infer<typeof providerDescription>;
export interface Adapter {
  readonly id: string; readonly source: string;
  describe(): ProviderDescription;
  capabilities(): Record<string, Json>;
  targets(): Promise<Json[]>;
  observe(target: string): Promise<State>;
  validateAction(state: State, action: Action): void;
  execute(target: string, state: State, action: Action, signal?: AbortSignal): Promise<State>;
  close(): Promise<void>;
  /** Optional, bounded image of the same observation; never capture on retrieval. */
  image?(revision: string): { data: string; mimeType: "image/jpeg" } | undefined;
}
export class ComputerUseError extends Error {
  constructor(readonly code: string, message: string, readonly details?: Record<string, Json>) { super(message); this.name = "ComputerUseError"; }
}
export function fail(code: string, message: string): never { throw new ComputerUseError(code, message); }
export function exactParams(params: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(params).some(key => !keys.includes(key))) fail("INVALID_ACTION", "Unexpected action parameters");
}
