import { computed, ref } from 'vue'
import type { desktopApi } from '../../api/desktop'
import type { UpdateInstallImpactDto, UpdateStatusDto } from '../../types'

type InstallApi = Pick<typeof desktopApi, 'startUpdate' | 'updateStatus' | 'updateInstallImpact' | 'installUpdate'>

export function useUpdateInstaller(api: InstallApi) {
  const state = createInstallState()
  const refreshUpdateStatus = createStatusRefresher(api, state)
  const startUpdate = createDownloadAction(api, state)
  const prepareInstall = createInstallPreview(api, state)
  const confirmInstall = createInstallAction(api, state)
  return { ...state, refreshUpdateStatus, startUpdate, prepareInstall, confirmInstall,
    cancelInstall() { if (!state.installing.value) state.installImpact.value = null },
    updating: computed(() => ['downloading', 'verifying', 'installing'].includes(state.updateStatus.value.state)) }
}

function createInstallState() {
  return { updateStatus: ref<UpdateStatusDto>({ state: 'idle', version: '', progress: 0,
    downloaded_bytes: 0, total_bytes: 0, message: '' }),
  installImpact: ref<UpdateInstallImpactDto | null>(null), installError: ref(''),
  installBusy: ref(false), installing: ref(false) }
}
type InstallState = ReturnType<typeof createInstallState>

function createStatusRefresher(api: InstallApi, state: InstallState) {
  let pending = false
  return async (initial = false) => {
    if (pending || state.installBusy.value) return
    if (!initial && !['downloading', 'verifying', 'installing'].includes(state.updateStatus.value.state)) return
    pending = true
    const before = state.updateStatus.value
    try {
      const status = await api.updateStatus()
      if (state.updateStatus.value === before && !state.installBusy.value) state.updateStatus.value = status
    }
    catch (error) { state.installError.value = error instanceof Error ? error.message : String(error) }
    finally { pending = false }
  }
}

function createDownloadAction(api: InstallApi, state: InstallState) {
  return async () => {
    if (state.installBusy.value || ['downloading', 'verifying', 'ready', 'installing'].includes(state.updateStatus.value.state)) return
    state.installBusy.value = true
    state.installError.value = ''
    try { state.updateStatus.value = await api.startUpdate() }
    catch (error) { state.installError.value = error instanceof Error ? error.message : String(error) }
    finally { state.installBusy.value = false }
  }
}

function createInstallPreview(api: InstallApi, state: InstallState) {
  return async () => {
    if (state.installBusy.value || state.updateStatus.value.state !== 'ready') return
    state.installBusy.value = true
    state.installError.value = ''
    try { state.installImpact.value = await api.updateInstallImpact() }
    catch (error) { state.installError.value = error instanceof Error ? error.message : String(error) }
    finally { state.installBusy.value = false }
  }
}

function createInstallAction(api: InstallApi, state: InstallState) {
  return async () => {
    const impact = state.installImpact.value
    if (!impact || state.installBusy.value) return
    state.installBusy.value = true
    state.installing.value = true
    state.installError.value = ''
    try {
      state.updateStatus.value = await api.installUpdate(impact.services.map(service => service.id))
      state.installImpact.value = null
    } catch (error) {
      state.installError.value = error instanceof Error ? error.message : String(error)
      state.installImpact.value = null
    } finally { state.installBusy.value = false; state.installing.value = false }
  }
}
