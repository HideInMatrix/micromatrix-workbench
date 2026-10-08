// Adapted from ASIL softwaregen/runtime.py @ ca7706c, Apache-2.0; stricter RFC6901 and URL validation.
import { createHash } from "node:crypto";
import { fail, type Json } from "../protocol.js";

export const placeholder = /\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;
export const envPlaceholder = /\$\{ENV:([a-zA-Z_][a-zA-Z0-9_]*)\}/g;
export function validPointer(pointer: string): boolean { return pointer === "" || pointer.startsWith("/") && !/~(?:[^01]|$)/.test(pointer); }
export function resolveJsonPointer(document: Json, pointer: string): Json {
  if (!validPointer(pointer)) fail("INVALID_POINTER", "Malformed RFC6901 pointer");
  if (!pointer) return document;
  let current = document;
  for (const raw of pointer.slice(1).split("/")) {
    const key = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    if (Array.isArray(current)) {
      if (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) >= current.length) fail("MISSING_POINTER", "Array pointer not found");
      current = current[Number(key)]!;
    } else if (current !== null && typeof current === "object" && Object.hasOwn(current, key)) current = current[key]!;
    else fail("MISSING_POINTER", "Object pointer not found");
  }
  return current;
}
function argument(params: Record<string, Json>, name: string): Json {
  if (!Object.hasOwn(params, name)) fail("INVALID_ACTION", "Template argument missing");
  return params[name]!;
}
function scalar(value: Json): string {
  if (value !== null && typeof value === "object") fail("INVALID_ACTION", "Interpolated parameter must be scalar; use an exact placeholder for JSON values");
  // Match Python scalar rendering for embedded command/query templates.
  return value === null ? "None" : value === true ? "True" : value === false ? "False" : String(value);
}
export function renderTemplate(value: Json, params: Record<string, Json>): Json {
  if (typeof value === "string") {
    const exact = /^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$/.exec(value);
    if (exact) return structuredClone(argument(params, exact[1]!));
    // Validate the template, not replacement data (a user's literal '${...}' stays data).
    if (value.replace(placeholder, "").includes("${")) fail("INVALID_ACTION", "Unsupported template placeholder");
    return value.replace(placeholder, (_, name: string) => scalar(argument(params, name)));
  }
  if (Array.isArray(value)) return value.map(child => renderTemplate(child, params));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, renderTemplate(child, params)]));
  return value;
}
export function renderPathTemplate(value: string, params: Record<string, Json>): string {
  if (value.replace(placeholder, "").includes("${")) fail("INVALID_ACTION", "Unsupported path placeholder");
  return value.replace(placeholder, (_, name: string) => {
    const text = scalar(argument(params, name));
    if (text === "." || text === ".." || /[\/\\\0]/.test(text)) fail("INVALID_ACTION", "Path parameter must be a single segment");
    return encodeURIComponent(text).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  });
}
export function resolveEnvironment(value: string, env: Readonly<Record<string, string>>): string {
  if (value.replace(envPlaceholder, "").includes("${")) fail("INVALID_BINDINGS", "Malformed runtime variable reference");
  return value.replace(envPlaceholder, (_, name: string) => {
    if (!Object.hasOwn(env, name)) fail("INVALID_BINDINGS", "Required private runtime variable unavailable");
    return env[name]!;
  });
}
export function canonicalSha256(value: unknown): string {
  const sorted = (item: unknown): unknown => Array.isArray(item) ? item.map(sorted) : item && typeof item === "object"
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, child]) => [key, sorted(child)])) : item;
  return createHash("sha256").update(JSON.stringify(sorted(value))).digest("hex");
}
export function walkStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(walkStrings);
  return value && typeof value === "object" ? Object.values(value).flatMap(walkStrings) : [];
}
