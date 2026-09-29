export interface NetworkConfigDto {
  provider: string
  public_url: string
  options: Record<string, string>
}

export interface NetworkProviderOptionDto {
  key: string
  label: string
  secret: boolean
  span: '1' | '2'
}

export interface NetworkProviderDto {
  key: string
  label: string
  supports_public_url: boolean
  ephemeral_without_public_url: boolean
  options: NetworkProviderOptionDto[]
}

export interface RuntimeDto {
  runtime_id: string
  name: string
  workspace: string
  oauth_password: string
  has_saved_password: boolean
  host: string
  port: number
  enabled: boolean
  permission_mode: 'safe' | 'trusted' | 'dangerous'
  network: NetworkConfigDto
  running: boolean
  public_mcp_url: string
  url_mode: string
  exit_reason: string
}

export interface RuntimeDraft {
  name: string
  workspace: string
  oauth_password: string
  host: string
  port: number
  enabled: boolean
  remember_secrets: boolean
  permission_mode: 'safe' | 'trusted' | 'dangerous'
  network: NetworkConfigDto
}

export interface BootstrapDto {
  app_name: string
  version: string
  runtime: RuntimeDto
  network_providers: NetworkProviderDto[]
}

export interface LogEntryDto {
  id: number
  time: number
  message: string
}

export interface PermissionRequestDto {
  request_id: string
  runtime_id: string
  runtime_name: string
  tool_name: string
  permission: string
  reason: string
  arguments: Record<string, unknown> | unknown[]
  created_at: number
  expires_at: number
}

export interface BodyPluginDto {
  id: string
  name: string
  enabled: boolean
  required: boolean
}

export interface SkillSummaryDto {
  id: string
  name: string
  description: string
  usage_hint: string
  recommended_capabilities: string[]
  version: number
  scope: 'built-in' | 'global'
  artifacts: string[]
}

export interface MCPConnectionSummaryDto {
  id: string
  name: string
  transport: 'stdio' | 'http'
  endpoint: string
  command: string
  enabled: boolean
  version: number
  tool_count: number
  last_discovered_at: number
  last_error: string
  health_tool: string
  scope: 'global'
}

export interface EffectiveToolDto {
  provider: 'system' | 'mcp'
  tool_name: string
  description: string
  input_schema: Record<string, unknown>
  key: string
  connection_id?: string
  connection_name?: string
}

export interface CapabilityDto {
  id: string
  type: 'builtin_tool' | 'skill' | 'mcp_tool'
  name: string
  description: string
  usage_hint?: string
  recommended_capabilities?: string[]
  recommended_capability_status?: {
    resolved: string[]
    unresolved: string[]
    ok: boolean
  }
  dependencies?: Array<{
    capability_id: string
    relation: string
    required: boolean
  }>
  dependents?: Array<{
    capability_id: string
    relation: string
    required: boolean
  }>
  input_schema: Record<string, unknown>
  tags?: string[]
  source: Record<string, unknown>
  availability: {
    status: 'available' | 'degraded' | 'unavailable'
    reasons: Array<{
      code: string
      message?: string
      capability_ids?: string[]
    }>
  }
  execution: {
    owner: 'workbench_runtime' | 'desktop_host' | 'external_mcp' | 'ai_client'
    required_capabilities: string[]
    required_operation_permissions: string[]
    annotations: {
      read_only: boolean
      destructive: boolean
      idempotent: boolean
      open_world: boolean
    }
    permission_boundary: string
    approval_boundary: string
  }
  invocation: Record<string, unknown>
}

export interface CapabilityCatalogDto {
  skills: SkillSummaryDto[]
  tools: string[]
  effective_tools: EffectiveToolDto[]
  mcp_connections: MCPConnectionSummaryDto[]
  capabilities: CapabilityDto[]
  revision: string
}
