import type { NetworkConfigDto, ServerDraft, ServerDto } from '../../types'

export type WorkItem = {
  key: string
  id: string
  server: ServerDto
}

export function cloneNetwork(network: NetworkConfigDto): NetworkConfigDto {
  return { ...network, options: { ...network.options } }
}

export function emptyWorkDraft(port: number): ServerDraft {
  return {
    name: '',
    workspace: '',
    oauth_password: '',
    host: '127.0.0.1',
    port,
    enabled: false,
    remember_secrets: true,
    permission_mode: 'safe',
    allow_network: false,
    enable_view_image: true,
    toolchains: [],
    network: { provider: 'cloudflare', public_url: '', options: {} },
  }
}

export function workDraft(server: ServerDto): ServerDraft {
  return {
    name: server.name,
    workspace: server.workspace,
    oauth_password: server.oauth_password,
    host: server.host,
    port: server.port,
    enabled: server.enabled,
    remember_secrets: server.has_saved_password
      || Object.keys(server.network.options).some(key => ['tunnel_token', 'authtoken'].includes(key)),
    permission_mode: server.permission_mode,
    allow_network: server.allow_network,
    enable_view_image: server.enable_view_image,
    toolchains: (server.toolchains || []).map(item => ({
      ...item,
      read_roots: [...item.read_roots],
    })),
    network: cloneNetwork(server.network),
  }
}

export function normalizedWorkDraft(value: ServerDraft): ServerDraft {
  const network = cloneNetwork(value.network)
  network.public_url = network.public_url.trim().replace(/\/+$/, '')
  return {
    ...value,
    name: value.name.trim(),
    workspace: value.workspace.trim(),
    network,
  }
}

export function workName(item: WorkItem): string {
  return item.server.name
}

export function workPort(item: WorkItem): number {
  return item.server.port
}

export function workRunning(item: WorkItem): boolean {
  return item.server.running
}

export function workEnabled(item: WorkItem): boolean {
  return item.server.enabled
}

export function workRuntimeUrl(server: ServerDto | ServerDraft): string {
  if ('public_mcp_url' in server && server.public_mcp_url) return server.public_mcp_url
  const base = server.network.public_url.trim().replace(/\/+$/, '')
  return base ? `${base}/mcp` : ''
}
