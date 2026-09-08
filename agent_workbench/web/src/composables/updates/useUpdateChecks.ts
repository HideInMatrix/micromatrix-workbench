import { computed, ref } from 'vue'
import type { desktopApi } from '../../api/desktop'
import type { ReleaseDto } from '../../types'

type CheckApi = Pick<typeof desktopApi, 'appVersion' | 'updateDownloadProxy' | 'updateCheckState' | 'checkUpdate' | 'saveUpdateDownloadProxy'>

export function useUpdateChecks(api: CheckApi, now: () => number = Date.now) {
  const state = createCheckState()
  const initialize = createInitializer(api, state)
  const checkUpdate = createChecker(api, state, initialize, now)
  const saveUpdateProxy = createProxySaver(api, state, initialize)
  return { ...state, initialize, checkUpdate, saveUpdateProxy,
    updateAvailable: computed(() => Boolean(state.release.value?.update_available)) }
}

function createCheckState() {
  return { version: ref(''), release: ref<ReleaseDto | null>(null), lastCheckedAt: ref(0),
    checkingUpdate: ref(false), updateProxyPrefix: ref(''), savingUpdateProxy: ref(false), errorMessage: ref('') }
}
type CheckState = ReturnType<typeof createCheckState>

function createInitializer(api: CheckApi, state: CheckState) {
  let pending: Promise<void> | undefined
  return () => {
    pending ??= Promise.all([api.appVersion(), api.updateDownloadProxy(), api.updateCheckState()])
      .then(([version, proxy, cached]) => {
        state.version.value = version
        state.updateProxyPrefix.value = proxy
        state.release.value = cached.release
        state.lastCheckedAt.value = cached.last_checked_at * 1000
      }).catch((error: unknown) => { pending = undefined; throw error })
    return pending
  }
}

function createChecker(api: CheckApi, state: CheckState, initialize: () => Promise<void>, now: () => number) {
  let pending: Promise<void> | undefined
  return async (manual = true): Promise<boolean> => {
    if (manual) state.errorMessage.value = ''
    try {
      await initialize()
      if (state.savingUpdateProxy.value) return false
      pending ??= (async () => {
        state.checkingUpdate.value = true
        state.release.value = await api.checkUpdate(manual)
        state.lastCheckedAt.value = now()
      })().finally(() => { pending = undefined; state.checkingUpdate.value = false })
      await pending
      return true
    } catch (error) {
      if (manual) state.errorMessage.value = error instanceof Error ? error.message : String(error)
      return false
    }
  }
}

function createProxySaver(api: CheckApi, state: CheckState, initialize: () => Promise<void>) {
  return async (prefix: string) => {
    if (state.savingUpdateProxy.value || state.checkingUpdate.value) return
    state.savingUpdateProxy.value = true
    state.errorMessage.value = ''
    try {
      await initialize()
      state.updateProxyPrefix.value = await api.saveUpdateDownloadProxy(prefix)
      state.release.value = null
      state.lastCheckedAt.value = 0
    } catch (error) {
      state.errorMessage.value = error instanceof Error ? error.message : String(error)
    } finally { state.savingUpdateProxy.value = false }
  }
}
