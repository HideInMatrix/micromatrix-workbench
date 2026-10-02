import { getVersion } from '@tauri-apps/api/app'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { controlBaseUrl } from './controlUrl'
import { waitForControlService } from './serviceReadiness'
import type {
  BootstrapDto,
  BodyPluginDto,
  CapabilityCatalogDto,
  LogEntryDto,
  PermissionRequestDto,
  RuntimeConfigurationDto,
  RuntimeDto,
  SavedRuntimeSecrets,
} from '../types'

interface DesktopApiRequest {
  method: string
  args: unknown[]
}

const controlUrl = controlBaseUrl({
  configured: import.meta.env.VITE_CONTROL_URL,
  development: import.meta.env.DEV,
  tauri: isTauri(),
  origin: window.location.origin,
})

let controlReady: Promise<void> | null = null
async function waitForDesktopControl() {
  if (!isTauri()) return
  if (!controlReady) {
    controlReady = waitForControlService({
      diagnostic: () => invoke<string | null>('desktop_service_error'),
      probe: async () => {
        const response = await fetch(`${controlUrl}/healthz`, { signal: AbortSignal.timeout(1000) })
        if (!response.ok) throw new Error(`控制服务健康检查失败：HTTP ${response.status}`)
        if ((await response.json()).ok !== true) throw new Error('控制服务健康检查返回了无效响应')
        return true
      },
      delay: () => new Promise(resolve => window.setTimeout(resolve, 150)),
    }).catch(error => { controlReady = null; throw error })
  }
  await controlReady
}

async function call<T>(method: string, ...args: unknown[]): Promise<T> {
  await waitForDesktopControl()
  const request: DesktopApiRequest = { method, args }
  const response = await fetch(`${controlUrl}/api/desktop`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request),
    ...(method === 'list_permission_requests' ? { signal: AbortSignal.timeout(5000) } : {}),
  })
  if (!response.ok) {
    const body = await response.text()
    let message = body
    try {
      const parsed: unknown = JSON.parse(body)
      if (parsed && typeof parsed === 'object' && typeof Reflect.get(parsed, 'error') === 'string') {
        message = Reflect.get(parsed, 'error') as string
      }
    } catch {
      // Preserve a non-JSON response as the diagnostic message.
    }
    throw new Error(message || `Desktop API ${method} failed: HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const desktopApi = {
  bootstrap: () => call<BootstrapDto>('bootstrap'),
  appVersion: () => isTauri() ? getVersion() : call<string>('get_app_version'),
  runtime: () => call<RuntimeDto>('get_runtime'),
  configureRuntime: (payload: RuntimeConfigurationDto) => call<RuntimeDto>('configure_runtime', payload),
  startRuntime: () => call<RuntimeDto>('start_runtime'),
  stopRuntime: () => call<RuntimeDto>('stop_runtime'),
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
  savedRuntimeSecrets: () => isTauri() ? invoke<SavedRuntimeSecrets>('runtime_saved_secrets') : Promise.resolve(null),
  async showPermissionPrompt(): Promise<void> {
    if (isTauri()) await invoke('show_permission_prompt')
  },
  async chooseWorkspace(initial = ''): Promise<string> {
    if (!isTauri()) return call<string>('choose_workspace', initial)
    const selected = await open({ directory: true, multiple: false, ...(initial ? { defaultPath: initial } : {}) })
    return typeof selected === 'string' ? selected : ''
  },
}
