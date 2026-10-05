import { z } from "zod";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Element {
  id: string; type: string; label: string; value?: Json; editable: boolean;
  available_actions: string[]; children: string[]; metadata?: Record<string, Json>;
}
export interface State {
  revision: string; app_state: Record<string, Json>; interactive_elements: Element[];
  environment: Record<string, Json>; navigation: Json[]; data_summary: string;
}
export interface Observation extends State {
  meta: { protocol: "micromatrix-asil/1"; adapter: string; source: string; target: string; observation_id: string; observed_at: string; expires_at: string; untrusted_content: true };
}
export const observationInput = z.object({ adapter: z.enum(["desktop", "json"]), target: z.string().min(1).max(2048) }).strict();
export const actionInput = z.object({
  observation_id: z.string().uuid(), action_type: z.enum(["navigate", "invoke_function", "set_value", "modify_file"]),
  target: z.string().min(1).max(2048), params: z.record(z.string(), z.json()),
  expect_observation: z.object({ target: z.string().min(1).max(2048), value: z.json() }).strict().optional(),
}).strict();
export type Action = z.infer<typeof actionInput>;
export interface Adapter {
  readonly id: "desktop" | "json"; readonly source: string;
  capabilities(): Record<string, Json>;
  targets(): Promise<Json[]>;
  observe(target: string): Promise<State>;
  validateAction(state: State, action: Action): void;
  execute(target: string, state: State, action: Action, signal?: AbortSignal): Promise<State>;
  close(): Promise<void>;
}
export class ComputerUseError extends Error {
  constructor(readonly code: string, message: string) { super(message); this.name = "ComputerUseError"; }
}
export function fail(code: string, message: string): never { throw new ComputerUseError(code, message); }
export function exactParams(params: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(params).some(key => !keys.includes(key))) fail("INVALID_ACTION", "Unexpected action parameters");
}
