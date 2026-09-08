export const UPDATE_CHECK_INTERVAL = 24 * 60 * 60 * 1000
export const UPDATE_STARTUP_DELAY = 10_000
const RETRY_DELAY = 60 * 60 * 1000
const MAX_RETRY_DELAY = 6 * RETRY_DELAY

export interface UpdateClock {
  now(): number
  setTimeout(callback: () => void, delay: number): number
  clearTimeout(timer: number): void
}

export function createUpdateScheduler(check: () => Promise<boolean>, lastChecked: () => number, clock: UpdateClock) {
  const state = { stopped: true, timer: 0, retryAt: 0, failures: 0, pending: false, startupAt: 0 }
  const schedule = (delay: number) => {
    clock.clearTimeout(state.timer)
    if (!state.stopped) state.timer = clock.setTimeout(() => { void tick() }, Math.max(1, delay))
  }
  const tick = async () => {
    if (state.stopped || state.pending) return
    const last = lastChecked()
    const due = last > 0 && last <= clock.now() ? last + UPDATE_CHECK_INTERVAL : 0
    const wait = Math.max(due, state.retryAt, state.startupAt) - clock.now()
    if (wait > 0) { schedule(wait); return }
    state.pending = true
    let success = false
    try { success = await check() }
    catch { success = false } // Background failures use bounded retries without interrupting the user.
    finally {
      state.pending = false
      state.failures = success ? 0 : state.failures + 1
      const retry = Math.min(MAX_RETRY_DELAY, RETRY_DELAY * 2 ** Math.min(state.failures - 1, 3))
      state.retryAt = success ? 0 : clock.now() + retry
      schedule(success ? UPDATE_CHECK_INTERVAL : retry)
    }
  }
  return {
    start() { state.stopped = false; state.startupAt = clock.now() + UPDATE_STARTUP_DELAY; schedule(UPDATE_STARTUP_DELAY) },
    stop() { state.stopped = true; clock.clearTimeout(state.timer) },
    wake() { if (!state.stopped) void tick() },
  }
}
