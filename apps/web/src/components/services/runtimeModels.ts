import type { NetworkConfigDto, RuntimeDraft, RuntimeDto } from '../../types'

export function cloneNetwork(network: NetworkConfigDto): NetworkConfigDto {
  return { ...network, options: { ...network.options } }
}

export function emptyRuntimeDraft(): RuntimeDraft {
  return {
    name: 'Pi MCP Runtime',
    workspace: '',
    oauth_password: '',
    host: '127.0.0.1',
    port: 8234,
    enabled: false,
    remember_secrets: true,
    permission_mode: 'safe',
    network: { provider: 'cloudflare', public_url: '', options: {} },
  }
}

export function runtimeDraft(runtime: RuntimeDto): RuntimeDraft {
  return {
    name: runtime.name,
    workspace: runtime.workspace,
    oauth_password: runtime.oauth_password,
    host: runtime.host,
    port: runtime.port,
    enabled: runtime.enabled,
    remember_secrets: runtime.has_saved_password
      || Object.keys(runtime.network.options).some(key => ['tunnel_token', 'auth_token'].includes(key)),
    permission_mode: runtime.permission_mode,
    network: cloneNetwork(runtime.network),
  }
}

export function normalizedRuntimeDraft(value: RuntimeDraft): RuntimeDraft {
  const network = cloneNetwork(value.network)
  network.public_url = network.public_url.trim().replace(/\/+$/, '')
  return {
    ...value,
    name: value.name.trim(),
    workspace: value.workspace.trim(),
    network,
  }
}

export function runtimeUrl(runtime: RuntimeDto | RuntimeDraft): string {
  if ('public_mcp_url' in runtime && runtime.public_mcp_url) return runtime.public_mcp_url
  const base = runtime.network.public_url.trim().replace(/\/+$/, '')
  return base ? `${base}/mcp` : ''
}
