import { computed, reactive, ref } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { Update } from '@tauri-apps/plugin-updater'
import { relaunch } from '@tauri-apps/plugin-process'
import { toast } from 'vue-sonner'
import { desktopApi } from '../api/desktop'
import { createUpdateController, emptyUpdateState } from '../api/updateController'

export const updateInstallationLocked = ref(false)
const state = reactive(emptyUpdateState())
const native = isTauri()
const downloadPrefix = ref('https://cdn.gh-proxy.org/')
const prefixDraft = ref(downloadPrefix.value)
const savingPrefix = ref(false)
let preferencesReady: Promise<void> | null = null
let announcedVersion = ''
interface UpdatePreferences { download_proxy_prefix: string }
interface UpdateMetadata { rid: number; currentVersion: string; version: string; body?: string; rawJson: Record<string, unknown> }

async function loadPreferences() {
  if (!native) return
  if (!preferencesReady) preferencesReady = (async () => {
    const settings = await invoke<UpdatePreferences>('get_update_preferences')
    if (prefixDraft.value === downloadPrefix.value) prefixDraft.value = settings.download_proxy_prefix
    downloadPrefix.value = settings.download_proxy_prefix
  })().catch(error => { preferencesReady = null; throw error })
  return preferencesReady
}
const controller = createUpdateController(state, {
  check: async () => {
    await loadPreferences()
    const metadata = await invoke<UpdateMetadata | null>('check_update_with_prefix')
    return metadata ? new Update(metadata) : null
  },
  stopRuntime: () => desktopApi.stopRuntime(),
  relaunch,
  installationLock: value => { updateInstallationLocked.value = value },
})
const busy = computed(() => savingPrefix.value || ['checking', 'downloading', 'installing'].includes(state.phase))
const progress = computed(() => state.total ? Math.min(100, Math.round(state.downloaded / state.total * 100)) : null)

async function check() {
  if (!native || savingPrefix.value) return
  await controller.check()
  if (state.phase === 'available' && state.version !== announcedVersion) {
    announcedVersion = state.version
    toast.info(`发现新版本 ${state.version}，可在“关于”中手动更新。`)
  }
}
async function savePrefix() {
  if (!native || busy.value || state.phase === 'installed') return
  const requestedPrefix = prefixDraft.value
  savingPrefix.value = true
  try {
    await loadPreferences()
    const settings = await invoke<UpdatePreferences>('save_update_preferences', { prefix: requestedPrefix })
    downloadPrefix.value = prefixDraft.value = settings.download_proxy_prefix
    await controller.reset() // Recheck explicitly before obtaining a new download resource.
    toast.success('下载加速前缀已保存。')
  } catch (error) { state.error = error instanceof Error ? error.message : String(error) }
  finally { savingPrefix.value = false }
}

export function useAppUpdater() {
  return { state, native, busy, progress, prefixDraft, downloadPrefix, savingPrefix,
    updateAvailable: computed(() => Boolean(state.version) && ['available', 'error'].includes(state.phase)),
    loadPreferences: async () => {
      try { await loadPreferences() } catch (error) { state.error = error instanceof Error ? error.message : String(error) }
    },
    savePrefix, check,
    install: () => native && !savingPrefix.value ? controller.install() : Promise.resolve(),
    restart: () => native ? controller.restart() : Promise.resolve(),
  }
}
