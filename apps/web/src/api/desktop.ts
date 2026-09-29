import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import type {
  BootstrapDto,
  BodyPluginDto,
  CapabilityCatalogDto,
  LogEntryDto,
  PermissionRequestDto,
  RuntimeDraft,
  RuntimeDto,
} from '../types'

interface DesktopApiRequest {
  method: string
  args: unknown[]
}

const controlUrl = (import.meta.env.VITE_CONTROL_URL || 'http://127.0.0.1:8233').replace(/\/$/, '')

async function call<T>(method: string, ...args: unknown[]): Promise<T> {
  const request: DesktopApiRequest = { method, args }
  const response = await fetch(`${controlUrl}/api/desktop`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Desktop API ${method} failed: HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const desktopApi = {
  bootstrap: () => call<BootstrapDto>('bootstrap'),
  appVersion: () => call<string>('get_app_version'),
  runtime: () => call<RuntimeDto>('get_runtime'),
  configureRuntime: (payload: RuntimeDraft) => call<RuntimeDto>('configure_runtime', payload),
  startRuntime: () => call<RuntimeDto>('start_runtime'),
  stopRuntime: () => call<RuntimeDto>('stop_runtime'),
  setRuntimeEnabled: (enabled: boolean) => call<RuntimeDto>('set_runtime_enabled', enabled),
  listBodyPlugins: () => call<BodyPluginDto[]>('list_body_plugins'),
  setBodyPluginEnabled: (pluginId: string, enabled: boolean) =>
    call<boolean>('set_body_plugin_enabled', pluginId, enabled),
  listPermissionRequests: () => call<PermissionRequestDto[]>('list_permission_requests'),
  respondPermissionRequest: (
    requestId: string,
    decision: 'deny' | 'once' | 'session',
  ) => call<boolean>('respond_permission_request', requestId, decision),
  capabilityCatalog: () => call<CapabilityCatalogDto>('get_workbench_capability_catalog'),
  logs: (after = 0) => call<{ cursor: number; entries: LogEntryDto[] }>('get_logs', after),
  clearLogs: () => call<number>('clear_logs'),
  async chooseWorkspace(initial = ''): Promise<string> {
    if (!isTauri()) return call<string>('choose_workspace', initial)
    const selected = await open({ directory: true, multiple: false, ...(initial ? { defaultPath: initial } : {}) })
    return typeof selected === 'string' ? selected : ''
  },
}
