import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { desktopApi } from '../api/desktop'
import {
  emptyRuntimeDraft,
  normalizedRuntimeDraft,
  runtimeDraft,
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
const busy = ref(false)
const lifecycleBusy = ref(false)
const enabling = ref(false)
const errorMessage = ref('')
const copiedUrl = ref('')
const tunnelTokenVisible = ref(false)
const oauthPasswordVisible = ref(false)
let pollTimer = 0
let initializePromise: Promise<void> | null = null

export function useRuntimeManager() {
  const running = computed(() => Boolean(runtime.value?.running))
  const locked = running

  async function refreshRuntime() {
    runtime.value = await desktopApi.runtime()
  }

  async function chooseWorkspace() {
    if (locked.value) return
    const value = await desktopApi.chooseWorkspace(draft.value.workspace)
    if (value) draft.value.workspace = value
  }

  function validateDraft(value: RuntimeDraft) {
    if (!value.name) throw new Error('Runtime 名称不能为空。')
    if (!value.workspace) throw new Error('Runtime 必须选择工作目录。')
  }

  async function persistDraft(): Promise<RuntimeDto> {
    const value = normalizedRuntimeDraft(draft.value)
    validateDraft(value)
    const saved = await desktopApi.configureRuntime(value)
    runtime.value = saved
    draft.value = runtimeDraft(saved)
    return saved
  }

  async function saveRuntime() {
    if (busy.value || locked.value) return
    busy.value = true
    errorMessage.value = ''
    try {
      await persistDraft()
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally {
      busy.value = false
    }
  }

  async function setEnabled(enabled: boolean) {
    if (enabling.value) return
    enabling.value = true
    errorMessage.value = ''
    try {
      const updated = await desktopApi.setRuntimeEnabled(enabled)
      runtime.value = updated
      draft.value.enabled = updated.enabled
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally {
      enabling.value = false
    }
  }

  async function toggleRunning() {
    if (busy.value || lifecycleBusy.value) return
    lifecycleBusy.value = true
    errorMessage.value = ''
    try {
      if (running.value) {
        runtime.value = await desktopApi.stopRuntime()
      } else {
        await persistDraft()
        runtime.value = await desktopApi.startRuntime()
      }
      if (runtime.value) draft.value = runtimeDraft(runtime.value)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
      try { await refreshRuntime() } catch { /* preserve the original error */ }
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

  async function pollRuntime() {
    if (!ready.value) {
      await initialize()
      return
    }
    if (busy.value || lifecycleBusy.value || enabling.value) return
    try { await refreshRuntime() } catch { /* transient polling failure */ }
  }

  async function initialize() {
    if (ready.value) return
    if (initializePromise) return initializePromise
    initializing.value = true
    initializePromise = (async () => {
      try {
        const snapshot = await desktopApi.bootstrap()
        runtime.value = snapshot.runtime
        networkProviders.value = snapshot.network_providers
        draft.value = runtimeDraft(snapshot.runtime)
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
    busy,
    lifecycleBusy,
    enabling,
    errorMessage,
    copiedUrl,
    tunnelTokenVisible,
    oauthPasswordVisible,
    running,
    locked,
    runtimeUrl: computed(() => runtime.value ? runtimeUrl(runtime.value) : runtimeUrl(draft.value)),
    chooseWorkspace,
    saveRuntime,
    setEnabled,
    toggleRunning,
    copyUrl,
  }
}
