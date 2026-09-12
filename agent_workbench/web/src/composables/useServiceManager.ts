import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { desktopApi } from '../api/desktop'
import {
  emptyWorkDraft,
  normalizedWorkDraft,
  workDraft,
  workEnabled,
  workName,
  workPort,
  workRunning,
  workRuntimeUrl,
  type WorkItem,
} from '../components/services/serviceModels'
import type { NetworkProviderDto, ServerDraft, ServerDto } from '../types'

function cloneToolchains(server: ServerDto) {
  return (server.toolchains || []).map(item => ({
    ...item,
    read_roots: [...item.read_roots],
  }))
}

// Work state intentionally lives outside the route component. Router switches
// unmount ServiceView, but startup/bootstrap may still be in flight. Keeping
// the state here prevents a route change from discarding the completed
// bootstrap result and forcing the page back into an empty "new Work" state.
const servers = ref<ServerDto[]>([])
const networkProviders = ref<NetworkProviderDto[]>([])
const selectedKey = ref('')
const draft = ref<ServerDraft>(emptyWorkDraft(8234))
const isNew = ref(true)
const ready = ref(false)
const initializing = ref(false)
const busy = ref(false)
const lifecycleBusy = ref(false)
const togglingId = ref('')
const errorMessage = ref('')
const copiedUrl = ref('')
const tunnelTokenVisible = ref(false)
const oauthPasswordVisible = ref(false)
let pollTimer = 0
let initializePromise: Promise<void> | null = null

export function useServiceManager() {
  const works = computed<WorkItem[]>(() => servers.value.map(server => ({
    key: `work:${server.server_id}`,
    id: server.server_id,
    server,
  })))
  const selected = computed(() => (
    works.value.find(item => item.key === selectedKey.value) || null
  ))
  const selectedRunning = computed(() => Boolean(selected.value?.server.running))
  const locked = computed(() => selectedRunning.value)
  const stats = computed(() => ({
    works: works.value.length,
    running: works.value.filter(workRunning).length,
  }))

  async function refreshWorks(preserveSelection = true) {
    const previous = selectedKey.value
    servers.value = await desktopApi.listServers()
    if (preserveSelection && previous && works.value.some(item => item.key === previous)) return
    if (!isNew.value) selectedKey.value = works.value[0]?.key || ''
  }

  async function selectWork(key: string, persistSelection = true) {
    const work = works.value.find(item => item.key === key)
    if (!work) return
    selectedKey.value = key
    isNew.value = false
    tunnelTokenVisible.value = false
    oauthPasswordVisible.value = false
    draft.value = workDraft(work.server)
    if (persistSelection) {
      try {
        await desktopApi.selectServer(work.id)
      } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : String(error)
      }
    }
  }

  async function createNew() {
    selectedKey.value = ''
    isNew.value = true
    tunnelTokenVisible.value = false
    oauthPasswordVisible.value = false
    draft.value = emptyWorkDraft(await desktopApi.nextPort())
  }

  async function chooseWorkspace() {
    if (locked.value) return
    const value = await desktopApi.chooseWorkspace(draft.value.workspace)
    if (value) draft.value.workspace = value
  }

  async function persistDraft(): Promise<string> {
    const value = normalizedWorkDraft(draft.value)
    if (!value.name) throw new Error('Work 名称不能为空。')
    if (!value.workspace) throw new Error('Work 必须选择工作目录。')
    if (isNew.value) {
      const created = await desktopApi.createServer(value)
      return `work:${created.server_id}`
    }
    const current = selected.value
    if (!current) throw new Error('找不到当前 Work。')
    const updated = await desktopApi.updateServer(current.id, value)
    return `work:${updated.server_id}`
  }

  async function saveWork() {
    if (busy.value || locked.value) return
    busy.value = true
    errorMessage.value = ''
    try {
      const key = await persistDraft()
      isNew.value = false
      await refreshWorks(false)
      await selectWork(key)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally {
      busy.value = false
    }
  }

  async function deleteWork() {
    const current = selected.value
    if (!current || current.server.running) return
    if (!confirm('确定删除这个 Work 吗？相关运行与认证状态会一并清理。')) return
    busy.value = true
    errorMessage.value = ''
    try {
      await desktopApi.deleteServer(current.id)
      await refreshWorks(false)
      if (works.value.length) await selectWork(works.value[0].key)
      else await createNew()
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally {
      busy.value = false
    }
  }

  async function toggleWork(work: WorkItem, enabled: boolean) {
    if (togglingId.value) return
    togglingId.value = work.id
    errorMessage.value = ''
    try {
      await desktopApi.setServerEnabled(work.id, enabled)
      await refreshWorks(true)
      if (selectedKey.value === work.key) await selectWork(work.key)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
      await refreshWorks(true)
    } finally {
      togglingId.value = ''
    }
  }

  async function toggleRunning() {
    const current = selected.value
    if (!current || isNew.value || lifecycleBusy.value) return
    const key = current.key
    lifecycleBusy.value = true
    errorMessage.value = ''
    try {
      if (current.server.running) {
        await desktopApi.stopServer(current.id)
      } else {
        await desktopApi.startServer(current.id, normalizedWorkDraft(draft.value))
      }
      await refreshWorks(true)
      await selectWork(key)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
      await refreshWorks(true)
    } finally {
      lifecycleBusy.value = false
    }
  }

  async function copyUrl(value: string) {
    if (!value) return
    await navigator.clipboard.writeText(value)
    copiedUrl.value = value
    window.setTimeout(() => {
      if (copiedUrl.value === value) copiedUrl.value = ''
    }, 1500)
  }

  async function pollWorks() {
    if (!ready.value) {
      await initialize()
      return
    }
    if (busy.value || lifecycleBusy.value || togglingId.value) return
    try {
      await refreshWorks(true)
    } catch { /* transient polling failure */ }
  }

  async function initialize() {
    if (ready.value) return
    if (initializePromise) return initializePromise
    initializing.value = true
    initializePromise = (async () => {
      try {
        const snapshot = await desktopApi.bootstrap()
        servers.value = snapshot.servers
        networkProviders.value = snapshot.network_providers

        const preferredKey = snapshot.selected_server_id
          ? `work:${snapshot.selected_server_id}`
          : works.value[0]?.key || ''
        const preferred = works.value.find(item => item.key === preferredKey) || works.value[0]
        if (preferred) {
          await selectWork(preferred.key, false)
        } else {
          selectedKey.value = ''
          isNew.value = true
          tunnelTokenVisible.value = false
          oauthPasswordVisible.value = false
          draft.value = emptyWorkDraft(snapshot.next_default_port)
        }
        ready.value = true
        errorMessage.value = ''
      } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : String(error)
      } finally {
        initializing.value = false
        initializePromise = null
      }
    })()
    return initializePromise
  }

  async function syncRegisteredToolchain(event: Event) {
    const serverId = (event as CustomEvent<string>).detail
    try {
      await refreshWorks(true)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
      return
    }
    if (selected.value?.id !== serverId || isNew.value) return
    const saved = servers.value.find(item => item.server_id === serverId)
    if (saved) draft.value.toolchains = cloneToolchains(saved)
  }

  onMounted(() => {
    void initialize()
    if (!pollTimer) pollTimer = window.setInterval(() => void pollWorks(), 1000)
    window.addEventListener('toolchain-registered', syncRegisteredToolchain)
  })
  onBeforeUnmount(() => {
    if (pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = 0
    }
    window.removeEventListener('toolchain-registered', syncRegisteredToolchain)
  })

  return {
    servers,
    networkProviders,
    selectedKey,
    draft,
    isNew,
    ready,
    initializing,
    busy,
    lifecycleBusy,
    togglingId,
    errorMessage,
    copiedUrl,
    tunnelTokenVisible,
    oauthPasswordVisible,
    works,
    selected,
    selectedRunning,
    locked,
    stats,
    workName,
    workPort,
    workRunning,
    workEnabled,
    runtimeUrl: computed(() => selected.value
      ? workRuntimeUrl(selected.value.server)
      : workRuntimeUrl(draft.value)),
    selectWork,
    createNew,
    chooseWorkspace,
    saveWork,
    deleteWork,
    toggleWork,
    toggleRunning,
    copyUrl,
  }
}
