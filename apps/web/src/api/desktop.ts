import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { openUrl } from '@tauri-apps/plugin-opener'
import type {
  BootstrapDto,
  BodyPluginDto,
  CapabilityCatalogDto,
  LogEntryDto,
  PermissionRequestDto,
  ReleaseDto,
  ServerDraft,
  ServerDto,
  UpdateCheckStateDto,
  UpdateInstallImpactDto,
  UpdateStatusDto,
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
  updateDownloadProxy: () => call<string>('get_update_download_proxy'),
  saveUpdateDownloadProxy: (prefix: string) => call<string>('save_update_download_proxy', prefix),
  listServers: () => call<ServerDto[]>('list_servers'),
  selectServer: (serverId: string) => call<boolean>('select_server', serverId),
  createServer: (payload: ServerDraft) => call<ServerDto>('create_server', payload),
  updateServer: (serverId: string, payload: ServerDraft) =>
    call<ServerDto>('update_server', serverId, payload),
  startServer: (serverId: string, payload?: ServerDraft) =>
    call<ServerDto>('start_server', serverId, payload),
  stopServer: (serverId: string) => call<ServerDto>('stop_server', serverId),
  setServerEnabled: (serverId: string, enabled: boolean) =>
    call<ServerDto>('set_server_enabled', serverId, enabled),
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
  updateCheckState: () => call<UpdateCheckStateDto>('get_update_check_state'),
  updateInstallImpact: () => call<UpdateInstallImpactDto>('get_update_install_impact'),
  checkUpdate: (force = true) => call<ReleaseDto>('check_update', force),
  startUpdate: () => call<UpdateStatusDto>('start_update'),
  updateStatus: () => call<UpdateStatusDto>('update_status'),
  installUpdate: (confirmedServices: string[]) =>
    call<UpdateStatusDto>('install_update', confirmedServices),
  async openExternal(url: string): Promise<boolean> {
    if (!isTauri()) {
      window.open(url, '_blank', 'noopener,noreferrer')
      return true
    }
    await openUrl(url)
    return true
  },
}
