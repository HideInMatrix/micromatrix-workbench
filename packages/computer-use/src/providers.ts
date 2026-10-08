import { providerId, providerDescription, stateInput, fail, type Adapter, type ProviderDescription, type State } from "./protocol.js";

/** Only reviewed, host-supplied implementations. Never import paths from model/workspace input. */
export class ProviderRegistry {
  readonly #providers = new Map<string, { adapter: Adapter; description: ProviderDescription }>();
  constructor(adapters: readonly Adapter[]) {
    for (const adapter of adapters) {
      providerId.parse(adapter.id);
      if (adapter.id === "errors" || this.#providers.has(adapter.id)) fail("INVALID_PROVIDER", "Duplicate or reserved provider ID");
      if (!adapter.source || adapter.source.length > 128) fail("INVALID_PROVIDER", "Provider must declare a bounded state source");
      const description = providerDescription.parse(adapter.describe());
      if (new Set(description.actions.map(action => action.action_type)).size !== description.actions.length) fail("INVALID_PROVIDER", "Duplicate provider action description");
      this.#providers.set(adapter.id, { adapter, description });
    }
  }
  get(id: string): Adapter { return this.#providers.get(id)?.adapter ?? fail("UNSUPPORTED_ADAPTER", `Provider not registered: ${id}`); }
  description(id: string): ProviderDescription { this.get(id); return structuredClone(this.#providers.get(id)!.description); }
  list(): Adapter[] { return [...this.#providers.values()].map(entry => entry.adapter); }
}

export function checkedState(input: State): State {
  if (Buffer.byteLength(JSON.stringify(input)) > 1024 * 1024) fail("STATE_LIMIT", "Provider state exceeds 1 MiB");
  const state = stateInput.parse(input), ids = new Set(state.interactive_elements.map(element => element.id));
  if (ids.size !== state.interactive_elements.length) fail("INVALID_STATE", "Provider returned duplicate element IDs");
  if (state.interactive_elements.some(element => element.children.some(id => !ids.has(id)))) fail("INVALID_STATE", "Provider returned an unknown child element");
  return { ...state, interactive_elements: state.interactive_elements.map(({value, metadata, data_type, constraints, ...element}) => ({ ...element,
    ...(value === undefined ? {} : {value}), ...(metadata === undefined ? {} : {metadata}),
    ...(data_type === undefined ? {} : {data_type}), ...(constraints === undefined ? {} : {constraints}) })) };
}
