import { computed, onBeforeUnmount, onMounted, ref, type ComputedRef, type Ref } from 'vue'
import { desktopApi } from '../api/desktop'
import {
  directDraft,
  emptyDraft,
  emptyMember,
  gatewayDraft,
  normalizePath,
  normalizedGatewayDraft,
  serverDraft,
  serviceMode,
  serviceName,
  servicePort,
  serviceProfileCount,
  serviceRunning,
  type ServiceItem,
} from '../components/services/serviceModels'
import { isSelectedResourceStarting } from '../lib/serverState'
import type { GatewayDiagnosticDto, GatewayDraft, GatewayDto, GatewayMemberDraft, NetworkProviderDto, ServerDto } from '../types'

interface ServiceState {
  servers: Ref<ServerDto[]>
  gateways: Ref<GatewayDto[]>
  networkProviders: Ref<NetworkProviderDto[]>
  selectedKey: Ref<string>
  draft: Ref<GatewayDraft>
  isNew: Ref<boolean>
  busy: Ref<boolean>
  startingKey: Ref<string>
  errorMessage: Ref<string>
  copiedUrl: Ref<string>
  diagnostic: Ref<GatewayDiagnosticDto | null>
  tunnelTokenVisible: Ref<boolean>
  oauthPasswordVisibility: Ref<Map<GatewayMemberDraft, boolean>>
  pollTimer: Ref<number>
}

interface ServiceContext extends ServiceState {
  services: ComputedRef<ServiceItem[]>
  selected: ComputedRef<ServiceItem | null>
  locked: ComputedRef<boolean>
}

const diagnosticCheckLabels: Record<string, string> = {
  local_path_runtime: '本地 Gateway → Runtime',
  public_path_runtime: '公网 Hostname → Runtime',
  server_card: 'Server Card',
  oauth_authorization_metadata: 'OAuth Authorization Metadata',
  oauth_protected_resource: 'OAuth Protected Resource Metadata',
  mcp_auth_challenge: 'MCP 401 Auth Challenge',
  oauth_token_exchange: 'OAuth Authorization Code → Token',
}

function createServiceState(): ServiceState {
  return {
    servers: ref<ServerDto[]>([]),
    gateways: ref<GatewayDto[]>([]),
    networkProviders: ref<NetworkProviderDto[]>([]),
    selectedKey: ref(''),
    draft: ref<GatewayDraft>(emptyDraft(8234)),
    isNew: ref(true),
    busy: ref(false),
    startingKey: ref(''),
    errorMessage: ref(''),
    copiedUrl: ref(''),
    diagnostic: ref<GatewayDiagnosticDto | null>(null),
    tunnelTokenVisible: ref(false),
    oauthPasswordVisibility: ref(new Map<GatewayMemberDraft, boolean>()),
    pollTimer: ref(0),
  }
}

function createServices(state: ServiceState): ComputedRef<ServiceItem[]> {
  return computed(() => [
    ...state.servers.value.map(server => ({
      key: `direct:${server.server_id}`,
      kind: 'direct' as const,
      id: server.server_id,
      server,
    })),
    ...state.gateways.value.map(gateway => ({
      key: `gateway:${gateway.gateway_id}`,
      kind: 'gateway' as const,
      id: gateway.gateway_id,
      gateway,
    })),
  ])
}

function createServiceContext(state: ServiceState): ServiceContext {
  const services = createServices(state)
  const selected = computed(() => services.value.find(item => item.key === state.selectedKey.value) || null)
  const selectedRunning = computed(() => selected.value ? serviceRunning(selected.value) : false)
  const selectedIsStarting = computed(() => isSelectedResourceStarting(state.selectedKey.value, state.startingKey.value))
  const locked = computed(() => selectedRunning.value || selectedIsStarting.value)
  return { ...state, services, selected, locked }
}

export function diagnosticErrorText(value: string): string {
  const separator = value.indexOf(':')
  if (separator < 0) return value
  const key = value.slice(0, separator).trim()
  const detail = value.slice(separator + 1).trim()
  return `${diagnosticCheckLabels[key] || key}: ${detail}`
}

function isRootProfile(context: ServiceContext, member: GatewayMemberDraft, index: number): boolean {
  if (context.isNew.value) return index === 0
  const current = context.selected.value
  if (current?.kind === 'direct') return index === 0
  if (current?.kind !== 'gateway' || !member.server_id) return false
  return Boolean(current.gateway.members.find(item => (
    item.server_id === member.server_id && item.instance_path === ''
  )))
}

function runtimeUrl(context: ServiceContext, member: GatewayMemberDraft): string {
  const current = context.selected.value
  if (current?.kind === 'direct' && member.server_id === current.server.server_id) {
    if (current.server.public_mcp_url) return current.server.public_mcp_url
  }
  if (current?.kind === 'gateway' && member.server_id) {
    const runtime = current.gateway.members.find(item => item.server_id === member.server_id)
    if (runtime?.public_mcp_url) return runtime.public_mcp_url
  }
  const memberBase = member.public_url.trim().replace(/\/+$/, '')
  if (memberBase) return `${memberBase}/mcp`
  const base = context.draft.value.network.public_url.trim().replace(/\/+$/, '')
  return base ? `${base}${normalizePath(member.instance_path)}/mcp` : ''
}

function setMode(context: ServiceContext, mode: 'single' | 'multi') {
  if (context.locked.value || context.draft.value.mode === mode) return
  if (mode === 'single') {
    const hasRoot = context.draft.value.members.some((member, index) => isRootProfile(context, member, index))
    if (!hasRoot) {
      context.errorMessage.value = '当前服务没有主 Workspace，无法切换到单 Workspace。'
      return
    }
  }
  context.draft.value.mode = mode
  if (mode === 'multi' && context.draft.value.members.length === 1) {
    context.draft.value.members.push(emptyMember(1))
  }
}

async function refreshServices(context: ServiceContext, preserveSelection = true) {
  const previous = context.selectedKey.value
  const [servers, gateways] = await Promise.all([
    desktopApi.listServers(),
    desktopApi.listGateways(),
  ])
  context.servers.value = servers
  context.gateways.value = gateways
  if (preserveSelection && previous && context.services.value.some(item => item.key === previous)) return
  if (!context.isNew.value) context.selectedKey.value = context.services.value[0]?.key || ''
}

async function selectService(context: ServiceContext, key: string) {
  const service = context.services.value.find(item => item.key === key)
  if (!service) return
  context.tunnelTokenVisible.value = false
  context.oauthPasswordVisibility.value.clear()
  context.selectedKey.value = key
  context.isNew.value = false
  context.diagnostic.value = service.kind === 'gateway' ? service.gateway.diagnostic : null
  context.draft.value = service.kind === 'direct' ? directDraft(service.server) : gatewayDraft(service.gateway)
}

async function createNewService(context: ServiceContext) {
  context.tunnelTokenVisible.value = false
  context.oauthPasswordVisibility.value.clear()
  context.selectedKey.value = ''
  context.isNew.value = true
  context.diagnostic.value = null
  context.draft.value = emptyDraft(await desktopApi.nextPort())
}

function removeProfile(context: ServiceContext, index: number) {
  if (context.locked.value || context.draft.value.members.length <= 1) return
  const member = context.draft.value.members[index]
  if (isRootProfile(context, member, index)) return
  if (context.draft.value.mode === 'multi' && context.draft.value.members.length <= 2) {
    context.errorMessage.value = '多 Workspace 模式至少保留一个子 Profile。请先切换到单 Workspace，再删除最后一个子 Profile。'
    return
  }
  context.draft.value.members.splice(index, 1)
}

async function chooseWorkspace(context: ServiceContext, member: GatewayMemberDraft) {
  if (context.locked.value) return
  const value = await desktopApi.chooseWorkspace(member.workspace)
  if (value) member.workspace = value
}

async function persistDraft(context: ServiceContext): Promise<string> {
  const value = normalizedGatewayDraft(context.draft.value)
  if (!value.members.length) throw new Error('服务至少需要一个 Workspace。')
  const current = context.selected.value
  if (context.isNew.value) {
    if (value.mode === 'single' && value.members.length === 1 && value.members[0].instance_path === '') {
      const created = await desktopApi.createServer(serverDraft(value))
      return `direct:${created.server_id}`
    }
    const created = await desktopApi.createGateway(value)
    return `gateway:${created.gateway_id}`
  }
  if (!current) throw new Error('找不到当前服务。')
  if (current.kind === 'direct') return persistDirectService(current.id, value)
  const updated = await desktopApi.updateGateway(current.id, value)
  return `gateway:${updated.gateway_id}`
}

async function persistDirectService(serverId: string, value: GatewayDraft): Promise<string> {
  if (value.mode === 'single' && value.members.length === 1 && value.members[0].instance_path === '') {
    const updated = await desktopApi.updateServer(serverId, serverDraft(value))
    return `direct:${updated.server_id}`
  }
  const promoted = await desktopApi.promoteServerToGateway(serverId, value)
  return `gateway:${promoted.gateway_id}`
}

async function saveService(context: ServiceContext) {
  if (context.busy.value) return
  context.busy.value = true
  context.errorMessage.value = ''
  try {
    const key = await persistDraft(context)
    context.isNew.value = false
    await refreshServices(context, false)
    await selectService(context, key)
  } catch (error) {
    context.errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    context.busy.value = false
  }
}

async function deleteService(context: ServiceContext) {
  const current = context.selected.value
  if (!current || !confirm('确定删除这个服务吗？相关 OAuth 状态也会按现有清理规则处理。')) return
  context.busy.value = true
  context.errorMessage.value = ''
  try {
    if (current.kind === 'direct') await desktopApi.deleteServer(current.id)
    else await desktopApi.deleteGateway(current.id)
    await refreshServices(context, false)
    if (context.services.value.length) await selectService(context, context.services.value[0].key)
    else await createNewService(context)
  } catch (error) {
    context.errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    context.busy.value = false
  }
}

async function startSavedService(context: ServiceContext, key: string) {
  context.startingKey.value = key
  await refreshServices(context, false)
  await selectService(context, key)
  const saved = context.selected.value
  if (!saved) throw new Error('保存后的服务状态不可用。')
  const value = normalizedGatewayDraft(context.draft.value)
  if (saved.kind === 'direct') await desktopApi.startServer(saved.id, serverDraft(value))
  else await desktopApi.startGateway(saved.id, value)
}

async function toggleService(context: ServiceContext) {
  const current = context.selected.value
  if (!current || context.busy.value) return
  context.busy.value = true
  context.errorMessage.value = ''
  const starting = !serviceRunning(current)
  if (starting) context.startingKey.value = current.key
  try {
    if (starting) await startSavedService(context, await persistDraft(context))
    else if (current.kind === 'direct') await desktopApi.stopServer(current.id)
    else await desktopApi.stopGateway(current.id)
    await refreshServices(context, false)
    if (context.selectedKey.value) await selectService(context, context.selectedKey.value)
  } catch (error) {
    context.errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    context.startingKey.value = ''
    context.busy.value = false
  }
}

async function testService(context: ServiceContext) {
  const current = context.selected.value
  if (current?.kind !== 'gateway' || current.gateway.mode !== 'multi' || !current.gateway.running || context.busy.value) return
  context.busy.value = true
  context.errorMessage.value = ''
  try {
    context.diagnostic.value = await desktopApi.testGateway(current.id)
  } catch (error) {
    context.errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    context.busy.value = false
  }
}

async function copyUrl(context: ServiceContext, value: string) {
  if (!value) return
  await navigator.clipboard.writeText(value)
  context.copiedUrl.value = value
  window.setTimeout(() => {
    if (context.copiedUrl.value === value) context.copiedUrl.value = ''
  }, 1500)
}

async function pollServices(context: ServiceContext) {
  if (context.busy.value) return
  try {
    const currentKey = context.selectedKey.value
    await refreshServices(context, true)
    if (!currentKey || !context.services.value.some(item => item.key === currentKey)) return
    const current = context.services.value.find(item => item.key === currentKey)
    if (current?.kind === 'gateway' && current.gateway.diagnostic) {
      context.diagnostic.value = current.gateway.diagnostic
    }
  } catch { /* transient polling failure */ }
}

async function initializeServiceManager(context: ServiceContext) {
  try {
    context.networkProviders.value = await desktopApi.networkProviders()
    await refreshServices(context, false)
    if (context.services.value.length) await selectService(context, context.services.value[0].key)
    else await createNewService(context)
  } catch (error) {
    context.errorMessage.value = error instanceof Error ? error.message : String(error)
  }
  context.pollTimer.value = window.setInterval(() => pollServices(context), 1000)
}

export function useServiceManager() {
  const context = createServiceContext(createServiceState())
  const selectedRunning = computed(() => context.selected.value ? serviceRunning(context.selected.value) : false)
  const selectedIsStarting = computed(() => isSelectedResourceStarting(context.selectedKey.value, context.startingKey.value))
  const failedDiagnosticProfiles = computed(() => context.diagnostic.value?.profiles.filter(profile => !profile.ok) || [])
  const showDiagnostic = computed(() => {
    const selected = context.selected.value
    return selected?.kind === 'gateway'
      && selected.gateway.mode === 'multi'
      && selected.gateway.running
  })
  const stats = computed(() => ({
    services: context.services.value.length,
    running: context.services.value.filter(serviceRunning).length,
    workspaces: context.servers.value.length + context.gateways.value.reduce((sum, item) => sum + item.members.length, 0),
  }))
  onMounted(() => initializeServiceManager(context))
  onBeforeUnmount(() => window.clearInterval(context.pollTimer.value))
  return {
    ...context, selectedRunning, selectedIsStarting, failedDiagnosticProfiles, showDiagnostic, stats,
    serviceName, servicePort, serviceRunning, serviceProfileCount, serviceMode, normalizePath,
    diagnosticErrorText,
    runtimeUrl: (member: GatewayMemberDraft) => runtimeUrl(context, member),
    isRootProfile: (member: GatewayMemberDraft, index: number) => isRootProfile(context, member, index),
    profileEnabled: (member: GatewayMemberDraft, index: number) => isRootProfile(context, member, index) || context.draft.value.mode === 'multi',
    setMode: (mode: 'single' | 'multi') => setMode(context, mode),
    selectService: (key: string) => selectService(context, key), createNew: () => createNewService(context),
    addProfile: () => context.draft.value.members.push(emptyMember(context.draft.value.members.length)),
    removeProfile: (index: number) => removeProfile(context, index), chooseWorkspace: (member: GatewayMemberDraft) => chooseWorkspace(context, member),
    isOAuthPasswordVisible: (member: GatewayMemberDraft) => context.oauthPasswordVisibility.value.get(member) === true,
    toggleOAuthPassword: (member: GatewayMemberDraft) => context.oauthPasswordVisibility.value.set(member, context.oauthPasswordVisibility.value.get(member) !== true),
    saveService: () => saveService(context), deleteService: () => deleteService(context), toggleService: () => toggleService(context),
    testService: () => testService(context), copyUrl: (value: string) => copyUrl(context, value),
  }
}
