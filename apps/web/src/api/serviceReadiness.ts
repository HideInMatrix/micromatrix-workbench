export async function waitForControlService(options: {
  probe: () => Promise<boolean>
  diagnostic: () => Promise<string | null>
  delay: () => Promise<void>
  now?: () => number
  timeoutMs?: number
}): Promise<void> {
  const now = options.now ?? Date.now
  const deadline = now() + (options.timeoutMs ?? 10_000)
  let lastError = ''
  while (now() < deadline) {
    const error = await options.diagnostic()
    if (error) throw new Error(error)
    try {
      if (await options.probe()) return
    } catch (error) {
      // The UI can mount before the sidecar binds its control listener.
      lastError = error instanceof Error ? error.message : String(error)
    }
    await options.delay()
  }
  throw new Error(`本地控制服务未就绪，Runtime 和 Tunnel 尚未启动。请检查桌面服务状态后重试。${lastError ? `\n${lastError}` : ''}`)
}
