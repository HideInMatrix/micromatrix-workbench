<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../../api/desktop'
import { updateInstallationLocked } from '../../composables/useAppUpdater'
import type { ComputerUseStatusDto } from '../../types'

const props = defineProps<{ locked?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const status = ref<ComputerUseStatusDto | null>(null)
const applicationName = computed(() => status.value?.permission?.bundleId === 'org.micromatrix.computer-use.dev'
  ? 'micromatrix Computer Use Dev' : 'micromatrix Computer Use')
const busy = ref(false)
const loadingError = ref('')
let alive = false
let timer: ReturnType<typeof setInterval> | undefined
let watchUntil = 0
const granted = computed(() => status.value?.platform === 'macos'
  ? status.value.permission?.accessibility === true : status.value?.permission?.interactiveDesktop === true)
const locked = computed(() => busy.value || props.locked || status.value?.running || updateInstallationLocked.value)
const permissionLabel = computed(() => !status.value?.enabled ? '未启用'
  : loadingError.value || status.value.error ? '检测失败'
  : !status.value.permission ? '尚未检查'
  : granted.value ? '权限就绪' : status.value.platform === 'macos' ? '需要系统授权' : '需要解锁交互桌面')

async function refresh() {
  status.value = await desktopApi.computerUseStatus()
  loadingError.value = ''
}
async function check(request = false) {
  status.value = await desktopApi.checkComputerUsePermissions(request)
  loadingError.value = ''
  if (granted.value) watchUntil = 0
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
    else watchUntil = 0
  })
}
async function requestPermission() {
  await action(async () => {
    // This explicit button is the only path to a native permission prompt.
    await check(true)
    if (!granted.value) {
      await desktopApi.openComputerUseSettings()
      watchUntil = Date.now() + 120_000
    }
  })
}
async function returnedToApp() {
  if (!status.value?.enabled || !status.value.available || !status.value.supported || busy.value || updateInstallationLocked.value) return
  await action(() => check(false))
}
async function copyHelperPath() {
  await action(async () => { await navigator.clipboard.writeText(status.value!.helperPath); toast.success('应用路径已复制。') })
}
onMounted(() => {
  alive = true
  void action(async () => { await refresh(); if (alive && status.value?.enabled && status.value.available && status.value.supported) await check(false) })
  window.addEventListener('focus', returnedToApp)
  timer = setInterval(() => {
    if (!alive || busy.value || updateInstallationLocked.value) return
    busy.value = true
    void (async () => {
      try {
        await refresh() // Metadata only, never spawns the execution body.
        if (status.value?.enabled && Date.now() < watchUntil) await check(false)
      } catch (error) { loadingError.value = error instanceof Error ? error.message : String(error) }
      finally { busy.value = false }
    })()
  }, 2500)
})
onUnmounted(() => { alive = false; watchUntil = 0; if (timer) clearInterval(timer); window.removeEventListener('focus', returnedToApp) })
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
        <p v-if="!granted" class="text-xs leading-5">请为 <strong class="font-medium">{{ applicationName }}</strong> 开启辅助功能权限。</p>
        <div class="flex flex-wrap gap-2">
          <Button v-if="!granted" size="sm" :disabled="busy || !status.allowActions || updateInstallationLocked" @click="requestPermission">打开权限设置</Button>
          <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测</Button>
          <Button v-if="!granted" size="sm" variant="ghost" :disabled="busy || updateInstallationLocked" @click="action(() => desktopApi.revealComputerUseApp())">定位应用</Button>
        </div>
      </template>
      <template v-else>
        <p v-if="!granted" class="text-xs leading-5">请登录并解锁 Windows 桌面。</p>
        <p v-if="status.permission?.elevated" class="text-xs text-destructive">请以普通权限运行客户端。</p>
        <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">检查交互桌面</Button>
      </template>
      <Button v-if="!status.allowActions" size="sm" variant="outline" :disabled="locked" @click="toggle(true)">启用控制动作（保留本机审批）</Button>
      <p v-if="loadingError || status.error" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ loadingError || status.error }}</p>
      <details class="text-xs leading-5">
        <summary class="cursor-pointer text-muted-foreground">连接与授权详情</summary>
        <div class="mt-3 space-y-3 rounded-lg bg-secondary/50 p-3">
          <div>Pi 连接：{{ status.connected ? '已连接' : status.running ? '未连接' : '等待启动' }}</div>
          <template v-if="status.platform === 'macos'">
            <p>只授权 {{ applicationName }}，不是主程序、终端或 Blender。权限页未列出时，用“+”添加此应用；“定位应用”会在 Finder 中选中它。</p>
            <div v-if="status.permission?.bundleId">应用身份：<code>{{ status.permission.bundleId }}</code></div>
            <code class="block break-all">{{ status.helperPath }}</code>
            <Button size="sm" variant="outline" :disabled="busy" @click="copyHelperPath">复制应用路径</Button>
            <p v-if="status.permission?.signingMode === 'ad-hoc'">此构建为 ad-hoc 签名，更新后旧授权可能失效。若开关已开启但检测失败，移除旧 Computer Use 条目，再添加当前应用授权。</p>
            <p>新授予权限后先重新检测；运行中的连接仍报权限错误时，手动停止再启动 Runtime。新版系统可能称为“设备控制和数据访问”。</p>
          </template>
          <p v-else>Windows 使用 UI Automation，不绕过 UAC、锁屏或高权限应用限制。</p>
          <p>控制动作仍按 Runtime 权限模式审批。首次启用后刷新网页 MCP 工具；Blender 自绘界面的完整建模能力需专用适配器。</p>
        </div>
      </details>
    </div>
  </section>
</template>
