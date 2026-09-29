import assert from 'node:assert/strict'
import test from 'node:test'
import { useUpdateChecks } from '../src/composables/updates/useUpdateChecks.ts'
import { useUpdateInstaller } from '../src/composables/updates/useUpdateInstaller.ts'
import { createUpdateScheduler, UPDATE_CHECK_INTERVAL as DAY, UPDATE_STARTUP_DELAY as DELAY } from '../src/composables/updates/updateScheduler.ts'
import type { ReleaseDto, UpdateStatusDto, UpdateInstallImpactDto } from '../src/types.ts'

const release: ReleaseDto = { current_version: '1.0.0', latest_version: '1.1.0', tag_name: 'v1.1.0',
  release_url: 'https://example.com/release', asset_name: 'app', download_url: 'https://example.com/app',
  update_asset_name: 'update', update_download_url: 'https://example.com/update',
  checksum_url: 'https://example.com/checksum', update_available: true }
const initial: UpdateStatusDto = { state: 'idle', version: '', progress: 0, downloaded_bytes: 0, total_bytes: 0, message: '' }
const flush = () => new Promise<void>(resolve => setImmediate(resolve))
function fakeClock() {
  let time = 1_000_000_000
  let nextId = 0
  const timers = new Map<number, { at: number; callback: () => void }>()
  return {
    now: () => time,
    setTimeout(callback: () => void, delay: number) { const id = ++nextId; timers.set(id, { at: time + delay, callback }); return id },
    clearTimeout(id: number) { timers.delete(id) }, count: () => timers.size,
    async advance(delay: number) {
      const target = time + delay
      while (true) {
        const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0]
        if (!next || next[1].at > target) break
        time = next[1].at; timers.delete(next[0]); next[1].callback(); await flush()
      }
      time = target; await flush()
    },
    jump(delay: number) { time += delay },
  }
}
function checkApi() {
  return { appVersion: async () => '1.0.0', updateDownloadProxy: async () => '',
    updateCheckState: async () => ({ release, last_checked_at: 1000 }),
    checkUpdate: async (_force = true) => release,
    saveUpdateDownloadProxy: async (prefix: string) => prefix }
}
function installApi() {
  return { startUpdate: async (): Promise<UpdateStatusDto> => ({ ...initial, state: 'downloading' }),
    updateStatus: async (): Promise<UpdateStatusDto> => ({ ...initial, state: 'ready', version: '1.1.0' }),
    updateInstallImpact: async (): Promise<UpdateInstallImpactDto> => ({ version: '1.1.0', services: [{ id: 'direct:one', name: '开发环境' }] }),
    installUpdate: async (_services: string[]): Promise<UpdateStatusDto> => ({ ...initial, state: 'installing' }) }
}
test('startup waits ten seconds, repeats after 24 hours, and disposes timers', async () => {
  const clock = fakeClock(); let last = 0; let calls = 0
  const scheduler = createUpdateScheduler(async () => { calls++; last = clock.now(); return true }, () => last, clock)
  scheduler.start(); scheduler.wake(); await clock.advance(DELAY - 1)
  assert.equal(calls, 0)
  await clock.advance(1); assert.equal(calls, 1)
  await clock.advance(DAY - 1); assert.equal(calls, 1)
  await clock.advance(1); assert.equal(calls, 2)
  scheduler.stop(); assert.equal(clock.count(), 0)
})
test('fresh persisted cache avoids startup checks; resume checks an expired cache once', async () => {
  const clock = fakeClock(); let last = clock.now() - 1000; let calls = 0
  const scheduler = createUpdateScheduler(async () => { calls++; last = clock.now(); return true }, () => last, clock)
  scheduler.start(); await clock.advance(DELAY); assert.equal(calls, 0)
  clock.jump(DAY); scheduler.wake(); scheduler.wake(); await flush(); assert.equal(calls, 1)
  scheduler.stop()
})
test('failures back off from one hour and do not spin on visibility events', async () => {
  const clock = fakeClock(); let calls = 0
  const scheduler = createUpdateScheduler(async () => { calls++; throw new Error('offline') }, () => 0, clock)
  scheduler.start(); await clock.advance(DELAY); scheduler.wake(); await flush(); assert.equal(calls, 1)
  await clock.advance(DAY / 24); assert.equal(calls, 2)
  await clock.advance(DAY / 24); assert.equal(calls, 2)
  await clock.advance(DAY / 24); assert.equal(calls, 3)
  scheduler.stop()
})
test('stopping an in-flight check prevents timer recreation', async () => {
  const clock = fakeClock(); let finish: (value: boolean) => void = () => {}
  const pending = new Promise<boolean>(resolve => { finish = resolve })
  const scheduler = createUpdateScheduler(() => pending, () => 0, clock)
  scheduler.start(); await clock.advance(DELAY); scheduler.stop(); finish(true); await flush()
  assert.equal(clock.count(), 0)
})
test('manual checks bypass recent cache; background failures preserve cache and stay quiet', async () => {
  const api = checkApi(); const calls: boolean[] = []
  api.checkUpdate = async force => { calls.push(force ?? true); throw new Error('offline') }
  const checks = useUpdateChecks(api, () => 2_000_000)
  await checks.initialize(); assert.equal(checks.updateAvailable.value, true)
  assert.equal(await checks.checkUpdate(false), false); assert.equal(checks.errorMessage.value, '')
  assert.equal(checks.lastCheckedAt.value, 1_000_000); assert.equal(checks.release.value?.latest_version, '1.1.0')
  await checks.checkUpdate(true); assert.deepEqual(calls, [false, true]); assert.equal(checks.errorMessage.value, 'offline')
})
test('concurrent manual and auto checks share one request; successful checks clear the badge', async () => {
  const api = checkApi(); let calls = 0; let finish: (value: ReleaseDto) => void = () => {}
  api.checkUpdate = () => { calls++; return new Promise(resolve => { finish = resolve }) }
  const checks = useUpdateChecks(api, () => 42_000)
  const automatic = checks.checkUpdate(false); await flush()
  const manual = checks.checkUpdate(true); await flush(); assert.equal(calls, 1)
  finish({ ...release, update_available: false }); await Promise.all([automatic, manual])
  assert.equal(checks.lastCheckedAt.value, 42_000); assert.equal(checks.updateAvailable.value, false)
  assert.equal(checks.checkingUpdate.value, false)
})
test('proxy edits invalidate cache and cannot race an active check', async () => {
  const checks = useUpdateChecks(checkApi()); await checks.initialize(); checks.checkingUpdate.value = true
  await checks.saveUpdateProxy('https://mirror.example.com/'); assert.equal(checks.updateProxyPrefix.value, '')
  checks.checkingUpdate.value = false; await checks.saveUpdateProxy('https://mirror.example.com/')
  assert.equal(checks.release.value, null); assert.equal(checks.lastCheckedAt.value, 0)
})
test('download completion never installs until a reviewed impact is explicitly confirmed', async () => {
  const api = installApi(); const calls: string[][] = []
  api.installUpdate = async services => { calls.push(services); return { ...initial, state: 'installing' } }
  const installer = useUpdateInstaller(api); await installer.startUpdate(); await installer.refreshUpdateStatus()
  assert.equal(installer.updateStatus.value.state, 'ready'); await installer.confirmInstall(); assert.deepEqual(calls, [])
  await installer.prepareInstall(); assert.equal(installer.installImpact.value?.services[0]?.name, '开发环境')
  installer.cancelInstall(); await installer.confirmInstall(); assert.deepEqual(calls, [])
  await installer.prepareInstall(); await installer.confirmInstall(); assert.deepEqual(calls, [['direct:one']])
})
test('changed services require another confirmation and ready status survives initialization', async () => {
  const api = installApi(); api.installUpdate = async () => { throw new Error('运行中的服务已变化') }
  const installer = useUpdateInstaller(api); await installer.refreshUpdateStatus(true)
  assert.equal(installer.updateStatus.value.state, 'ready'); await installer.prepareInstall(); await installer.confirmInstall()
  assert.equal(installer.installImpact.value, null); assert.equal(installer.installError.value, '运行中的服务已变化')
  assert.equal(installer.updateStatus.value.state, 'ready')
})

test('a slow initial status response cannot overwrite a newly started download', async () => {
  const api = installApi(); let finish: (status: UpdateStatusDto) => void = () => {}
  api.updateStatus = () => new Promise(resolve => { finish = resolve })
  const installer = useUpdateInstaller(api)
  const initializing = installer.refreshUpdateStatus(true)
  await installer.startUpdate()
  finish({ ...initial }); await initializing
  assert.equal(installer.updateStatus.value.state, 'downloading')
})
