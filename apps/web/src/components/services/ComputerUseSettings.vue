<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../../api/desktop'
import { updateInstallationLocked } from '../../composables/useAppUpdater'
import type { ComputerUseStatusDto } from '../../types'

const props = defineProps<{ locked?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const status = ref<ComputerUseStatusDto | null>(null)
const busy = ref(false)
const loadingError = ref('')
const granted = computed(() => status.value?.platform === 'macos'
  ? status.value.permission?.accessibility === true : status.value?.permission?.interactiveDesktop === true)
const locked = computed(() => busy.value || props.locked || status.value?.running || updateInstallationLocked.value)
const permissionLabel = computed(() => !status.value?.enabled ? '未启用'
  : loadingError.value || status.value.error ? '检测失败'
  : !status.value.permission ? '尚未检查'
  : status.value.platform === 'windows' && status.value.permission.elevated ? '请使用普通权限'
  : granted.value ? '权限就绪' : status.value.platform === 'macos' ? '需要系统授权' : '需要解锁交互桌面')

async function refresh() {
  status.value = await desktopApi.computerUseStatus()
  loadingError.value = ''
}
async function check(request = false) {
  status.value = await desktopApi.checkComputerUsePermissions(request)
  loadingError.value = ''
}
async function action(work: () => Promise<void>) {
  if (busy.value || updateInstallationLocked.value) return
  busy.value = true
  try { await work() }
  catch (error) { loadingError.value = error instanceof Error ? error.message : String(error); toast.error(loadingError.value) }
  finally { busy.value = false }
}
async function toggle(enabled: boolean) {
  if (locked.value) return
  await action(async () => {
    status.value = await desktopApi.setComputerUseEnabled(enabled)
    emit('changed')
    // Only check trust. Enabling never prompts, connects MCP, or starts a Tunnel.
    if (enabled) await check(false)
  })
}
async function requestPermission() {
  await action(async () => {
    // Keep the requesting application alive in its own permission window.
    // A transient IPC check is closed immediately and must not own onboarding.
    await desktopApi.openComputerUseSettings()
  })
}
// Mount reads cached metadata only. Permission checks are explicit, not timers
// or focus listeners: switching apps must not spawn helpers or disable buttons.
onMounted(() => { void action(refresh) })
defineExpose({ refresh: () => action(refresh) })
</script>

<template>
  <section class="rounded-xl border border-border bg-card p-4" aria-label="内置 Computer Use">
    <div class="flex items-center justify-between gap-4">
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <h2 class="m-0 text-sm font-medium">Computer Use</h2>
        <span v-if="status?.enabled" role="status" class="rounded-md bg-secondary px-2 py-0.5 text-xs text-muted-foreground">{{ permissionLabel }}</span>
        <span v-if="status?.enabled && !status.allowActions" class="text-xs text-muted-foreground">旧配置只读</span>
      </div>
      <Switch :model-value="status?.enabled ?? false" :disabled="locked || !status || (!status.enabled && (!status.supported || !status.available || status.conflict))"
        :title="status?.running ? '停止 Runtime 后可修改' : '启用电脑控制工具'" aria-label="启用内置 Computer Use" @update:model-value="toggle" />
    </div>
    <p v-if="!status" class="mt-3 text-xs text-muted-foreground">{{ loadingError || '正在读取配置…' }}</p>
    <p v-else-if="!status.supported || !status.available || status.conflict" role="alert" class="mt-3 text-xs text-destructive">{{ status.conflict ? 'computer_use ID 已被占用，请先为外部 MCP 改名。' : '原生 helper 缺失或系统不支持，请安装完整的桌面包。' }}</p>
    <div v-else-if="status.enabled" class="mt-3 space-y-3">
      <template v-if="status.platform === 'macos'">
        <div class="flex flex-wrap gap-2">
          <Button v-if="!granted" size="sm" :disabled="busy || !status.allowActions || updateInstallationLocked" @click="requestPermission">设置权限</Button>
          <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测</Button>
        </div>
      </template>
      <template v-else>
        <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测</Button>
      </template>
      <Button v-if="!status.allowActions" size="sm" variant="outline" :disabled="locked" @click="toggle(true)">启用控制动作（保留本机审批）</Button>
      <p v-if="loadingError || status.error" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ loadingError || status.error }}</p>
    </div>
  </section>
</template>
