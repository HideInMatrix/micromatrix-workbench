import { existsSync } from "node:fs";
import { exactParams, fail, type Action, type Adapter, type Json, type State } from "./protocol.js";
import { desktopPlatform, nativeHelperPath, type DesktopPlatform } from "./platform.js";
import { NativeDesktopChannel } from "./native-channel.js";

export interface DesktopBackend {
  request(operation: string, params?: Record<string, unknown>, signal?: AbortSignal): Promise<unknown>;
  close(): Promise<void>;
}

/** One semantic desktop proxy; only its native backend is selected by OS. */
export class DesktopProxy implements Adapter {
  readonly id = "desktop" as const;
  readonly source: string;
  readonly #backend: DesktopBackend;
  constructor(readonly platform: DesktopPlatform = desktopPlatform(), readonly helper = nativeHelperPath(platform), backend?: DesktopBackend) {
    this.source = platform.source;
    this.#backend = backend ?? new NativeDesktopChannel(helper);
  }
  capabilities(): Record<string, Json> {
    return { available: existsSync(this.helper), platform: this.platform.name,
      operations: ["navigate", "invoke_function", "set_value"], native_operations: [...this.platform.operations],
      limitation: this.platform.limitation };
  }
  permissions(request = false) { return this.#backend.request("permissions", { prompt: request }); }
  async targets() { return await this.#backend.request("targets") as Json[]; }
  async observe(target: string) { return await this.#backend.request("observe", { target }) as State; }
  validateAction(state: State, action: Action) {
    const node = state.interactive_elements.find(element => element.id === action.target);
    if (!node || node.metadata?.secure === true || !node.available_actions.includes(action.action_type)) fail("INVALID_ACTION", "Target/action not advertised or is secure");
    if (action.action_type === "navigate") exactParams(action.params, []);
    else if (action.action_type === "set_value") {
      exactParams(action.params, ["value"]);
      if (!node.editable || !["string", "number", "boolean"].includes(typeof action.params.value)
        || typeof action.params.value === "string" && action.params.value.length > 16_384) fail("INVALID_ACTION", "Use a bounded scalar on an editable nonsecure element");
    } else if (action.action_type === "invoke_function") {
      exactParams(action.params, ["operation"]);
      if (typeof action.params.operation !== "string" || !this.platform.operations.includes(action.params.operation)
        || !Array.isArray(node.metadata?.operations) || !node.metadata.operations.includes(action.params.operation)) fail("INVALID_ACTION", "Native operation not advertised for this platform/element");
    } else fail("INVALID_ACTION", "Desktop action unsupported");
  }
  async execute(target: string, state: State, action: Action, signal?: AbortSignal) {
    this.validateAction(state, action);
    return await this.#backend.request("act", { target, revision: state.revision, action }, signal) as State;
  }
  close() { return this.#backend.close(); }
}
