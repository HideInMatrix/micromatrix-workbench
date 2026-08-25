import type {
  GatewayDraft,
  GatewayDto,
  GatewayMemberDraft,
  NetworkConfigDto,
  ServerDraft,
  ServerDto,
} from '../../types'

export type ServiceItem =
  | { key: string; kind: 'direct'; id: string; server: ServerDto }
  | { key: string; kind: 'gateway'; id: string; gateway: GatewayDto }

export function emptyMember(index: number): GatewayMemberDraft {
  return {
    name: index === 0 ? '主 Workspace' : `Profile ${index + 1}`,
    workspace: '',
    oauth_password: '',
    instance_path: index === 0 ? '' : `/profile-${index + 1}`,
    public_url: '',
    permission_mode: 'safe',
    allow_network: false,
    enable_view_image: true,
  }
}

export function emptyDraft(port: number): GatewayDraft {
  return {
    name: '',
    mode: 'single',
    host: '127.0.0.1',
    port,
    remember_secrets: true,
    network: { provider: 'cloudflare', public_url: '', options: {} },
    members: [emptyMember(0)],
  }
}

export function directDraft(server: ServerDto): GatewayDraft {
  return {
    name: server.name,
    mode: 'single',
    host: server.host,
    port: server.port,
    remember_secrets: server.has_saved_password
      || Object.keys(server.network.options).some(key => ['tunnel_token', 'authtoken'].includes(key)),
    network: cloneNetwork(server.network),
    members: [{
      server_id: server.server_id,
      name: '主 Workspace',
      workspace: server.workspace,
      oauth_password: server.oauth_password,
      instance_path: '',
      public_url: server.network.public_url,
      permission_mode: server.permission_mode,
      allow_network: server.allow_network,
      enable_view_image: server.enable_view_image,
    }],
  }
}

export function gatewayDraft(gateway: GatewayDto): GatewayDraft {
  return {
    name: gateway.name,
    mode: gateway.mode,
    host: gateway.host,
    port: gateway.port,
    remember_secrets: gateway.members.some(member => member.has_saved_password)
      || Object.keys(gateway.network.options).some(key => ['tunnel_token', 'authtoken'].includes(key)),
    network: cloneNetwork(gateway.network),
    members: gateway.members.map(member => ({
      server_id: member.server_id,
      name: member.name,
      workspace: member.workspace,
      oauth_password: member.oauth_password,
      instance_path: member.instance_path,
      public_url: member.public_url,
      permission_mode: member.permission_mode,
      allow_network: member.allow_network,
      enable_view_image: member.enable_view_image,
    })),
  }
}

export function normalizePath(value: string): string {
  const trimmed = value.trim().replace(/^\/+|\/+$/g, '')
  return trimmed ? `/${trimmed}` : ''
}

export function normalizePublicUrl(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

export function cloneNetwork(network: NetworkConfigDto): NetworkConfigDto {
  return { ...network, options: { ...network.options } }
}

export function normalizedGatewayDraft(value: GatewayDraft): GatewayDraft {
  const network = cloneNetwork(value.network)
  network.public_url = normalizePublicUrl(network.public_url)
  return {
    ...value,
    network,
    members: value.members.map((member, index) => ({
      ...member,
      instance_path: normalizePath(member.instance_path),
      public_url: index === 0
        ? network.public_url
        : normalizePublicUrl(member.public_url),
    })),
  }
}

export function serverDraft(value: GatewayDraft): ServerDraft {
  const root = value.members[0]
  return {
    name: value.name,
    workspace: root.workspace,
    oauth_password: root.oauth_password,
    host: value.host,
    port: value.port,
    remember_secrets: value.remember_secrets,
    permission_mode: root.permission_mode,
    allow_network: root.allow_network,
    enable_view_image: root.enable_view_image,
    network: cloneNetwork(value.network),
  }
}

export function serviceName(item: ServiceItem): string {
  return item.kind === 'direct' ? item.server.name : item.gateway.name
}

export function servicePort(item: ServiceItem): number {
  return item.kind === 'direct' ? item.server.port : item.gateway.port
}

export function serviceRunning(item: ServiceItem): boolean {
  return item.kind === 'direct' ? item.server.running : item.gateway.running
}

export function serviceProfileCount(item: ServiceItem): number {
  return item.kind === 'direct' ? 1 : item.gateway.members.length
}

export function serviceMode(item: ServiceItem): 'single' | 'multi' {
  return item.kind === 'direct' ? 'single' : item.gateway.mode
}
