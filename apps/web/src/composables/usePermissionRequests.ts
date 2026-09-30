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

  async function refreshPermissionRequests(surfaceError = false) {
    try {
      permissionRequests.value = await desktopApi.listPermissionRequests()
    } catch (error) {
      if (surfaceError) toast.error(error instanceof Error ? error.message : String(error), { id: 'permission-refresh' })
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

  onMounted(async () => {
    await actions.refreshPermissionRequests(true)
    pollTimer = window.setInterval(() => void actions.refreshPermissionRequests(false), 900)
  })

  onBeforeUnmount(() => window.clearInterval(pollTimer))

  return {
    ...state,
    ...actions,
    permissionLabel,
  }
}
