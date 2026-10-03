import { computed, reactive, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { check } from '@tauri-apps/plugin-updater'
import { relaunch } from '@tauri-apps/plugin-process'
import { desktopApi } from '../api/desktop'
import { createUpdateController, emptyUpdateState } from '../api/updateController'

export const updateInstallationLocked = ref(false)
const state = reactive(emptyUpdateState())
const native = isTauri()
const controller = createUpdateController(state, {
  check: () => check({ timeout: 15_000 }),
  stopRuntime: () => desktopApi.stopRuntime(),
  relaunch,
  installationLock: value => { updateInstallationLocked.value = value },
})
const busy = computed(() => ['checking', 'downloading', 'installing'].includes(state.phase))
const progress = computed(() => state.total ? Math.min(100, Math.round(state.downloaded / state.total * 100)) : null)

export function useAppUpdater() {
  return { state, native, busy, progress,
    check: () => native ? controller.check({ installAutomatically: !import.meta.env.DEV }) : Promise.resolve(),
    install: () => native ? controller.install() : Promise.resolve(),
    restart: () => native ? controller.restart() : Promise.resolve(),
  }
}
