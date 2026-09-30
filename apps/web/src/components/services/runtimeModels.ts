import type {
  NetworkConfigDto,
  NetworkDraft,
  RuntimeConfigurationDto,
  RuntimeDraft,
  RuntimeDto,
  SecretAction,
  SecretUpdateDto,
} from '../../types'

export function cloneNetwork(network: NetworkConfigDto): NetworkConfigDto {
  return { ...network, options: { ...network.options }, configured_secrets: [...network.configured_secrets] }
}

function emptyNetworkDraft(): NetworkDraft {
  return {
    provider: 'cloudflare',
    public_url: '',
    options: {},
    configured_secrets: [],
    secret_actions: {},
  }
}

export function emptyRuntimeDraft(): RuntimeDraft {
  return {
    name: 'Pi MCP Runtime',
    workspace: '',
    oauth_password: '',
    oauth_password_configured: false,
    oauth_password_action: 'unchanged',
    host: '127.0.0.1',
    port: 8234,
    remember_secrets: true,
    permission_mode: 'safe',
    network: emptyNetworkDraft(),
  }
}

export function runtimeDraft(runtime: RuntimeDto): RuntimeDraft {
  return {
    name: runtime.name,
    workspace: runtime.workspace,
    oauth_password: '',
    oauth_password_configured: runtime.has_oauth_password,
    oauth_password_action: 'unchanged',
    host: runtime.host,
    port: runtime.port,
    remember_secrets: runtime.remember_secrets,
    permission_mode: runtime.permission_mode,
    network: {
      ...cloneNetwork(runtime.network),
      secret_actions: Object.fromEntries(runtime.network.configured_secrets.map(key => [key, 'unchanged' as const])),
    },
  }
}

function secretUpdate(action: SecretAction, value: string): SecretUpdateDto {
  return action === 'set' ? { action, value } : { action }
}

export function normalizedRuntimeDraft(value: RuntimeDraft): RuntimeConfigurationDto {
  const secretKeys = new Set([
    ...value.network.configured_secrets,
    ...Object.keys(value.network.secret_actions),
  ])
  return {
    name: value.name.trim(),
    workspace: value.workspace.trim(),
    oauth_password_update: secretUpdate(value.oauth_password_action, value.oauth_password),
    host: value.host,
    port: value.port,
    remember_secrets: value.remember_secrets,
    permission_mode: value.permission_mode,
    network: {
      provider: value.network.provider,
      public_url: value.network.public_url.trim().replace(/\/+$/, ''),
      options: { ...value.network.options },
      secret_updates: Object.fromEntries([...secretKeys].map(key => [
        key,
        secretUpdate(value.network.secret_actions[key] ?? 'unchanged', value.network.options[key] ?? ''),
      ])),
    },
  }
}

export function runtimeUrl(runtime: RuntimeDto): string {
  return runtime.running ? runtime.public_mcp_url : ''
}
