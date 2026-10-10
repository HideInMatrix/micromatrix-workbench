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
const lifecycleAction = ref<'start' | 'stop' | null>(null)
let lifecycleSequence = 0
let startupAbort: AbortController | null = null
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
    const previous = runtime.value
    const sequence = lifecycleSequence
    const wasRunning = Boolean(runtime.value?.running)
    const updated = await desktopApi.runtime()
    if (sequence !== lifecycleSequence || runtime.value !== previous) return
    runtime.value = updated
    if (wasRunning && !updated.running && updated.exit_reason && lifecycleAction.value !== 'stop') {
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
    const stopping = running.value || lifecycleAction.value === 'start'
    if (busy.value || lifecycleAction.value === 'stop' || (!stopping && updateInstallationLocked.value)) return
    const sequence = ++lifecycleSequence
    lifecycleAction.value = stopping ? 'stop' : 'start'
    lifecycleBusy.value = true
    if (stopping) startupAbort?.abort()
    else startupAbort = new AbortController()
    try {
      let updated: RuntimeDto
      if (stopping) {
        updated = await desktopApi.stopRuntime()
      } else {
        await persistDraft()
        if (sequence !== lifecycleSequence) return
        updated = await desktopApi.startRuntime(startupAbort!.signal)
      }
      if (sequence !== lifecycleSequence) return
      runtime.value = updated
      if (runtime.value) draft.value = runtimeDraft(runtime.value, draft.value)
      toast.success(runtime.value?.running ? 'Runtime 已启动。' : 'Runtime 已停止。')
    } catch (error) {
      if (sequence !== lifecycleSequence) return
      if (stopping) {
        // A lost stop response does not mean Stop failed. Confirm the local
        // Runtime state before presenting a transport error to the user.
        try {
          await refreshRuntime()
          if (runtime.value && !runtime.value.running) {
            toast.success('Runtime 已停止。')
            return
          }
        } catch { /* Report the original failure if state cannot be confirmed. */ }
      }
      toast.error(error instanceof Error && error.name === 'TimeoutError'
        ? '本机启停请求超时，结果尚未确认；正在重新读取状态。'
        : error instanceof Error ? error.message : String(error))
      // Aborting fetch alone does not cancel the server's startup transaction.
      if (!stopping) {
        try { await desktopApi.stopRuntime() } catch { /* status remains authoritative */ }
      }
      if (!stopping) try { await refreshRuntime() } catch { /* preserve the original error */ }
    } finally {
      if (sequence === lifecycleSequence) {
        lifecycleBusy.value = false
        lifecycleAction.value = null
        startupAbort = null
      }
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
    if (busy.value) return
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
    lifecycleAction,
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
