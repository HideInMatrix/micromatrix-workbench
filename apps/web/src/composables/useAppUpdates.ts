import { inject, onBeforeUnmount, onMounted, provide, watch, type InjectionKey } from 'vue'
import { desktopApi } from '../api/desktop'
import { useUpdateChecks } from './updates/useUpdateChecks'
import { useUpdateInstaller } from './updates/useUpdateInstaller'
import { createUpdateScheduler } from './updates/updateScheduler'

function createAppUpdates() {
  return { ...useUpdateChecks(desktopApi), ...useUpdateInstaller(desktopApi) }
}
const updateKey: InjectionKey<ReturnType<typeof createAppUpdates>> = Symbol('app-updates')

export function provideAppUpdates() {
  const updates = createAppUpdates()
  const scheduler = createUpdateScheduler(() => updates.checkUpdate(false), () => updates.lastCheckedAt.value, {
    now: Date.now, setTimeout: (callback, delay) => window.setTimeout(callback, delay),
    clearTimeout: timer => window.clearTimeout(timer),
  })
  let pollTimer = 0
  const wake = () => { if (document.visibilityState === 'visible') scheduler.wake() }
  watch(updates.lastCheckedAt, () => scheduler.wake())
  onMounted(() => {
    void updates.initialize().catch(() => undefined) // The delayed checker retries initialization quietly.
    void updates.refreshUpdateStatus(true)
    scheduler.start()
    pollTimer = window.setInterval(() => { void updates.refreshUpdateStatus() }, 900)
    window.addEventListener('online', wake)
    document.addEventListener('visibilitychange', wake)
  })
  onBeforeUnmount(() => {
    scheduler.stop()
    window.clearInterval(pollTimer)
    window.removeEventListener('online', wake)
    document.removeEventListener('visibilitychange', wake)
  })
  provide(updateKey, updates)
  return updates
}

export function useAppUpdates() {
  const updates = inject(updateKey)
  if (!updates) throw new Error('App updates must be provided by the application root.')
  return updates
}
