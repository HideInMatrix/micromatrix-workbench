import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { desktopApi } from '@/api/desktop'
import type { PermissionRequestDto } from '@/types'

const PERMISSION_LABELS: Record<string, string> = {
  workspace_write: '修改 Workspace 文件',
  shell_execute: '执行本地 Shell 命令',
  open_world: '执行开放环境工具',
}

function permissionLabel(permission: string) {
  return PERMISSION_LABELS[permission] || permission
}

function stringifyPermissionArguments(request: PermissionRequestDto | null) {
  if (!request) return ''
  try {
    return JSON.stringify(request.arguments, null, 2)
  } catch {
    return String(request.arguments)
  }
}

function createPermissionState() {
  const permissionRequests = ref<PermissionRequestDto[]>([])
  const permissionResponding = ref(false)
  const activePermissionRequest = computed(() => permissionRequests.value[0] || null)
  return {
    permissionRequests,
    permissionResponding,
    activePermissionRequest,
    permissionArguments: computed(() => stringifyPermissionArguments(activePermissionRequest.value)),
  }
}

function createPermissionActions(state: ReturnType<typeof createPermissionState>) {
  const { activePermissionRequest, permissionRequests, permissionResponding } = state
  let refreshing = false
  let wasReachable = false
  let failures = 0
  let notifiedRequestId = ''

  async function refreshPermissionRequests(surfaceError = false) {
    if (refreshing) return
    refreshing = true
    try {
      permissionRequests.value = await desktopApi.listPermissionRequests()
      wasReachable = true
      failures = 0
      toast.dismiss('permission-refresh')
      const requestId = activePermissionRequest.value?.request_id ?? ''
      if (requestId && requestId !== notifiedRequestId) {
        notifiedRequestId = requestId
        try { await desktopApi.showPermissionPrompt() } catch {
          toast.error('有工具请求等待批准，但窗口提醒失败；请在当前弹窗确认。', { id: 'permission-attention' })
        }
      }
      if (!requestId) notifiedRequestId = ''
    } catch (error) {
      failures += 1
      if (surfaceError || (wasReachable && failures === 3)) {
        toast.error(`审批连接失败，工具可能正在等待批准：${error instanceof Error ? error.message : String(error)}`, { id: 'permission-refresh', duration: Infinity })
      }
    } finally {
      refreshing = false
    }
  }

  async function respondPermission(decision: 'deny' | 'once' | 'session') {
    const request = activePermissionRequest.value
    if (!request || permissionResponding.value) return

    permissionResponding.value = true
    try {
      const accepted = await desktopApi.respondPermissionRequest(request.request_id, decision)
      if (!accepted) toast.error('授权请求已过期或不再有效。')
      await refreshPermissionRequests(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      permissionResponding.value = false
    }
  }

  return { refreshPermissionRequests, respondPermission }
}

export function usePermissionRequests() {
  const state = createPermissionState()
  const actions = createPermissionActions(state)
  let pollTimer = 0
  let disposed = false
  const refresh = () => void actions.refreshPermissionRequests(false)
  const onVisibility = () => { if (document.visibilityState === 'visible') refresh() }

  onMounted(async () => {
    // Runtime bootstrap owns startup diagnostics; do not emit a second toast
    // before the desktop control service has finished starting.
    await actions.refreshPermissionRequests(false)
    if (disposed) return
    pollTimer = window.setInterval(refresh, 900)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', onVisibility)
  })

  onBeforeUnmount(() => {
    disposed = true
    window.clearInterval(pollTimer)
    window.removeEventListener('focus', refresh)
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return {
    ...state,
    ...actions,
    permissionLabel,
  }
}
