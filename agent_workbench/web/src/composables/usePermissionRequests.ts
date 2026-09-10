import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { desktopApi } from '@/api/desktop'
import type { PermissionRequestDto } from '@/types'

const PERMISSION_LABELS: Record<string, string> = {
  network: '访问网络',
  destructive_command: '执行破坏性命令',
  git_metadata_write: '写入 Git 元数据',
  long_timeout: '延长执行时间',
  sensitive_env: '传入敏感环境变量',
  sandbox_env_override: '覆盖沙箱环境变量',
  shell_expansion: '使用 Shell 展开',
  inline_script: '执行内联脚本',
  privileged_executable: '启动外部 stdio MCP',
  browser_observe: '观察隔离浏览器会话',
  browser_control: '控制隔离浏览器会话',
  host_identity_use: '使用宿主身份执行',
  host_manage: '管理 Host Worker',
  toolchain_registration: '自动发现工具 · 确认并记住',
  write_generated_or_ignored: '写入生成或忽略文件',
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
  const errorMessage = ref('')
  const permissionRequests = ref<PermissionRequestDto[]>([])
  const permissionResponding = ref(false)
  const permissionMenuOpen = ref(false)
  const activePermissionRequest = computed(() => permissionRequests.value[0] || null)
  const permissionIs = (permission: string) => computed(() => activePermissionRequest.value?.permission === permission)
  return {
    errorMessage,
    permissionRequests,
    permissionResponding,
    permissionMenuOpen,
    activePermissionRequest,
    isToolchainRegistration: permissionIs('toolchain_registration'),
    isBrowserControl: permissionIs('browser_control'),
    isBrowserObserve: permissionIs('browser_observe'),
    isHostIdentityUse: permissionIs('host_identity_use'),
    isHostManage: permissionIs('host_manage'),
    permissionArguments: computed(() => stringifyPermissionArguments(activePermissionRequest.value)),
  }
}

function createPermissionActions(state: ReturnType<typeof createPermissionState>) {
  const { activePermissionRequest, errorMessage, permissionMenuOpen, permissionRequests, permissionResponding } = state

  async function refreshPermissionRequests(surfaceError = false) {
    try {
      permissionRequests.value = await desktopApi.listPermissionRequests()
      if (!permissionRequests.value.length) permissionMenuOpen.value = false
      if (surfaceError) errorMessage.value = ''
    } catch (error) {
      if (surfaceError) errorMessage.value = error instanceof Error ? error.message : String(error)
    }
  }

  async function respondPermission(decision: 'deny' | 'once' | 'session' | 'remember') {
    const request = activePermissionRequest.value
    if (!request || permissionResponding.value) return

    permissionResponding.value = true
    permissionMenuOpen.value = false
    try {
      const accepted = await desktopApi.respondPermissionRequest(request.request_id, decision)
      if (!accepted) errorMessage.value = '授权请求已过期或不再有效。'
      else if (decision === 'remember') {
        window.dispatchEvent(new CustomEvent('toolchain-registered', { detail: request.server_id }))
      }
      await refreshPermissionRequests(false)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
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
