export function controlBaseUrl(options: {
  configured?: string | undefined
  development: boolean
  tauri: boolean
  origin: string
}): string {
  const fallback = options.development || options.tauri
    ? 'http://127.0.0.1:8233'
    : options.origin
  return (options.configured || fallback).replace(/\/$/, '')
}
