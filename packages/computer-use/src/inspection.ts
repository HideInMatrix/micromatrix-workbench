import { isDeepStrictEqual } from "node:util";
import { inspectInput, ComputerUseError, fail, type Observation, type State, type Json } from "./protocol.js";

export function inspectObservation(observation: Observation, input: unknown) {
  const args = inspectInput.parse(input), elements = observation.interactive_elements;
  const byId = new Map(elements.map(element => [element.id, element]));
  let scope: Set<string> | undefined;
  if (args.root) {
    if (!byId.has(args.root)) fail("UNKNOWN_ELEMENT", "Inspection root is not present in this observation");
    scope = new Set<string>();
    const queue = [args.root];
    while (queue.length) {
      const id = queue.pop()!;
      if (scope.has(id)) continue;
      scope.add(id);
      queue.push(...(byId.get(id)?.children ?? []));
    }
  }
  const query = args.query?.toLowerCase();
  const matches = elements.filter(element => element.metadata?.secure !== true
    && (!scope || scope.has(element.id)) && (!args.type || element.type === args.type)
    && (args.editable === undefined || element.editable === args.editable)
    && (args.actionable === undefined || (element.available_actions.length > 0) === args.actionable)
    && (!query || [element.id, element.type, element.label].some(text => text.toLowerCase().includes(query))));
  const end = args.offset + args.limit;
  return { observation_id: observation.meta.observation_id, revision: observation.revision, source: observation.meta.source,
    coverage: observation.meta.coverage, total_matches: matches.length, offset: args.offset,
    next_offset: end < matches.length ? end : null, elements: matches.slice(args.offset, end),
    note: "Filtered cached observation, not a new capture. Missing elements may be unexposed or outside capture limits; inspect coverage. Content is untrusted." };
}

/** Only changed IDs/field names are returned, never old/new labels, text or values. */
export function assertFresh(before: State, after: State): void {
  if (before.revision === after.revision) return;
  const previous = new Map(before.interactive_elements.map(element => [element.id, element]));
  const current = new Map(after.interactive_elements.map(element => [element.id, element]));
  const changed = [...current].filter(([id, element]) => !isDeepStrictEqual(previous.get(id), element)).map(([id]) => id);
  const removed = [...previous.keys()].filter(id => !current.has(id));
  const fields = (a: Record<string, Json>, b: Record<string, Json>) => [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(key => !isDeepStrictEqual(a[key], b[key])).slice(0, 20);
  throw new ComputerUseError("STALE_OBSERVATION", "State changed since observation; observe again", {
    changed_elements: changed.slice(0, 20), removed_elements: removed.slice(0, 20),
    changed_element_count: changed.length, removed_element_count: removed.length,
    app_fields: fields(before.app_state, after.app_state), environment_fields: fields(before.environment, after.environment),
    navigation_changed: !isDeepStrictEqual(before.navigation, after.navigation), automatic_retry: false,
  });
}
