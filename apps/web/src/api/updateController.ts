import type { DownloadEvent } from '@tauri-apps/plugin-updater'

export interface UpdatePackage {
  version: string
  body?: string
  download(onEvent: (event: DownloadEvent) => void, options: { timeout: number }): Promise<void>
  install(): Promise<void>
  close(): Promise<void>
}
export interface UpdateState {
  phase: 'idle' | 'checking' | 'current' | 'available' | 'downloading' | 'installing' | 'installed' | 'error'
  version: string
  notes: string
  error: string
  downloaded: number
  total: number
  lastCheckedAt: number
}
export const emptyUpdateState = (): UpdateState => ({ phase: 'idle', version: '', notes: '', error: '', downloaded: 0, total: 0, lastCheckedAt: 0 })

// The updater never starts Runtime. Download/signature verification completes
// before stopping execution; only the user's Install action starts this path.
export function createUpdateController(state: UpdateState, dependencies: {
  check(): Promise<UpdatePackage | null>
  stopRuntime(): Promise<unknown>
  relaunch(): Promise<void>
  installationLock(value: boolean): void
}) {
  let update: UpdatePackage | null = null
  let busy = false
  let installed = false
  const fail = (error: unknown) => {
    state.error = error instanceof Error ? error.message : String(error)
    state.phase = installed ? 'installed' : 'error'
  }
  async function check() {
    if (busy || installed) return
    busy = true
    state.phase = 'checking'
    state.error = ''
    state.version = state.notes = ''
    try {
      const previous = update
      update = null
      if (previous) await previous.close()
      update = await dependencies.check()
      state.version = update?.version ?? ''
      state.notes = update?.body ?? ''
      state.phase = update ? 'available' : 'current'
      state.lastCheckedAt = Date.now()
    } catch (error) { fail(error) } finally { busy = false }
  }
  async function install() {
    if (busy || !update || installed) return
    busy = true
    state.error = ''
    state.downloaded = state.total = 0
    // Lock configuration and Start before downloading, preventing a concurrent
    // user Start from racing shutdown/installation. Existing work keeps running.
    dependencies.installationLock(true)
    try {
      state.phase = 'downloading'
      await update.download(event => {
        if (event.event === 'Started') state.total = event.data.contentLength ?? 0
        if (event.event === 'Progress') state.downloaded += event.data.chunkLength
      }, { timeout: 300_000 })
      state.phase = 'installing'
      await dependencies.stopRuntime()
      await update.install()
      installed = true
      state.phase = 'installed'
      await dependencies.relaunch()
    } catch (error) { fail(error) } finally {
      busy = false
      // Once installed, keep execution locked until restart: the old process
      // must not spawn a service from a now-replaced application bundle.
      dependencies.installationLock(installed)
    }
  }
  return {
    check,
    install,
    async reset() {
      if (busy || installed) return
      const previous = update
      update = null
      state.phase = 'idle'; state.version = state.notes = state.error = ''; state.lastCheckedAt = 0
      if (previous) await previous.close()
    },
    async restart() {
      if (busy || !installed) return
      busy = true
      state.error = ''
      try { await dependencies.relaunch() } catch (error) { fail(error) } finally { busy = false }
    },
  }
}
