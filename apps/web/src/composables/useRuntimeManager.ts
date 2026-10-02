import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { updateInstallationLocked } from './useAppUpdater'
import { desktopApi } from '../api/desktop'
import {
  emptyRuntimeDraft,
  normalizedRuntimeDraft,
  runtimeDraft,
  restoreSavedSecrets,
  runtimeUrl,
} from '../components/services/runtimeModels'
import type { NetworkProviderDto, RuntimeDraft, RuntimeDto } from '../types'

// Runtime state intentionally outlives the route component so navigation does
// not discard a bootstrap request that is still in flight.
const runtime = ref<RuntimeDto | null>(null)
const networkProviders = ref<NetworkProviderDto[]>([])
const draft = ref<RuntimeDraft>(emptyRuntimeDraft())
const ready = ref(false)
const initializing = ref(false)
const initializationError = ref('')
const busy = ref(false)
const lifecycleBusy = ref(false)
const copiedUrl = ref('')
const tunnelTokenVisible = ref(false)
const oauthPasswordVisible = ref(false)
let pollTimer = 0
let initializePromise: Promise<void> | null = null
let initializationErrorShown = false

export function useRuntimeManager() {
  const running = computed(() => Boolean(runtime.value?.running))
  const locked = computed(() => running.value || lifecycleBusy.value || busy.value || updateInstallationLocked.value)

  async function refreshRuntime() {
    const wasRunning = Boolean(runtime.value?.running)
    const updated = await desktopApi.runtime()
    runtime.value = updated
    if (wasRunning && !updated.running && updated.exit_reason) {
      toast.error(updated.exit_reason, { id: 'runtime-unexpected-exit' })
    }
  }

  async function chooseWorkspace() {
    if (locked.value) return
    try {
      const value = await desktopApi.chooseWorkspace(draft.value.workspace)
      if (value) draft.value.workspace = value
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  function validateDraft(value: Pick<RuntimeDraft, 'name' | 'workspace'>) {
    if (!value.name) throw new Error('Runtime 名称不能为空。')
    if (!value.workspace) throw new Error('Runtime 必须选择工作目录。')
  }

  async function persistDraft(): Promise<RuntimeDto> {
    const value = normalizedRuntimeDraft(draft.value)
    validateDraft(value)
    const saved = await desktopApi.configureRuntime(value)
    runtime.value = saved
    draft.value = runtimeDraft(saved, draft.value)
    return saved
  }

  async function saveRuntime() {
    if (busy.value || locked.value) return
    busy.value = true
    try {
      await persistDraft()
      toast.success('Runtime 配置已保存。')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      busy.value = false
    }
  }

  async function toggleRunning() {
    if (busy.value || lifecycleBusy.value || updateInstallationLocked.value) return
    lifecycleBusy.value = true
    try {
      if (running.value) {
        runtime.value = await desktopApi.stopRuntime()
      } else {
        await persistDraft()
        runtime.value = await desktopApi.startRuntime()
      }
      if (runtime.value) draft.value = runtimeDraft(runtime.value, draft.value)
      toast.success(runtime.value?.running ? 'Runtime 已启动。' : 'Runtime 已停止。')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
      try { await refreshRuntime() } catch { /* preserve the original error */ }
    } finally {
      lifecycleBusy.value = false
    }
  }

  async function copyUrl(value: string) {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      toast.success('MCP 地址已复制。')
      copiedUrl.value = value
      window.setTimeout(() => {
        if (copiedUrl.value === value) copiedUrl.value = ''
      }, 1500)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  async function pollRuntime() {
    if (!ready.value) {
      if (initializationError.value) return
      await initialize()
      return
    }
    if (busy.value || lifecycleBusy.value) return
    try { await refreshRuntime() } catch { /* transient polling failure */ }
  }

  async function initialize() {
    if (ready.value) return
    if (initializePromise) return initializePromise
    initializing.value = true
    initializationError.value = ''
    initializePromise = (async () => {
      try {
        const snapshot = await desktopApi.bootstrap()
        runtime.value = snapshot.runtime
        networkProviders.value = snapshot.network_providers
        draft.value = runtimeDraft(snapshot.runtime)
        try {
          const secrets = await desktopApi.savedRuntimeSecrets()
          if (secrets) draft.value = restoreSavedSecrets(draft.value, secrets)
        } catch {
          toast.error('已保存的密钥未能回填；现有服务密钥仍保留，可重新输入。', { id: 'secret-restore' })
        }
        ready.value = true
        initializationErrorShown = false
      } catch (error) {
        initializationError.value = error instanceof Error ? error.message : String(error)
        if (!initializationErrorShown) {
          toast.error(initializationError.value, { id: 'runtime-initialize' })
          initializationErrorShown = true
        }
      } finally {
        initializing.value = false
        initializePromise = null
      }
    })()
    return initializePromise
  }

  onMounted(() => {
    void initialize()
    if (!pollTimer) pollTimer = window.setInterval(() => void pollRuntime(), 1000)
  })
  onBeforeUnmount(() => {
    if (pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = 0
    }
  })

  return {
    runtime,
    networkProviders,
    draft,
    ready,
    initializing,
    initializationError,
    busy,
    lifecycleBusy,
    copiedUrl,
    tunnelTokenVisible,
    oauthPasswordVisible,
    running,
    locked,
    runtimeUrl: computed(() => runtime.value ? runtimeUrl(runtime.value) : ''),
    chooseWorkspace,
    initialize,
    saveRuntime,
    toggleRunning,
    copyUrl,
  }
}
