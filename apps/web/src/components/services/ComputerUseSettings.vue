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
  await action(async () => { await navigator.clipboard.writeText(status.value!.helperPath); toast.success('原生 helper 路径已复制。') })
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
        <span class="rounded-md bg-secondary px-2 py-0.5 text-xs text-muted-foreground">内置</span>
        <span v-if="status?.enabled && !status.allowActions" class="text-xs text-muted-foreground">旧配置只读</span>
      </div>
      <Switch :model-value="status?.enabled ?? false" :disabled="locked || !status || (!status.enabled && (!status.supported || !status.available || status.conflict))"
        aria-label="启用内置 Computer Use" @update:model-value="toggle" />
    </div>
    <p v-if="!status" class="mt-3 text-xs text-muted-foreground">{{ loadingError || '正在读取插件配置…' }}</p>
    <p v-else-if="!status.supported || !status.available || status.conflict" role="alert" class="mt-3 text-xs text-destructive">{{ status.conflict ? '自定义 MCP 占用了 computer_use ID，请先改名。不会覆盖原服务。' : '当前系统不支持或原生 helper 缺失，请安装完整的 macOS / Windows 桌面包。' }}</p>
    <template v-else>
      <p v-if="status.running" class="mt-3 text-xs text-muted-foreground">停止 Runtime 后可修改开关。</p>
      <div v-if="status.enabled" class="mt-4 space-y-4 border-t border-border pt-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg bg-secondary/50 px-3 py-2.5">
            <div class="text-xs text-muted-foreground">系统权限</div>
            <div role="status" class="mt-1 text-sm font-medium">{{ permissionLabel }}</div>
          </div>
          <div class="rounded-lg bg-secondary/50 px-3 py-2.5">
            <div class="text-xs text-muted-foreground">Pi 连接</div>
            <div class="mt-1 text-sm font-medium">{{ status.connected ? '已连接' : status.running ? '未连接' : '等待启动' }}</div>
          </div>
        </div>
        <template v-if="status.platform === 'macos'">
          <ol v-if="!granted" class="list-decimal space-y-1.5 pl-5 text-xs leading-5">
            <li>打开系统设置 → 隐私与安全性 → 辅助功能。</li>
            <li>开启 micromatrix agent 或 micromatrix-computer 的权限。</li>
            <li>返回应用检测权限，再点击 Runtime 启动。</li>
          </ol>
          <div class="flex flex-wrap gap-2">
            <Button v-if="!granted" size="sm" :disabled="busy || !status.allowActions || updateInstallationLocked" @click="requestPermission">申请权限并打开系统设置</Button>
            <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测权限</Button>
          </div>
        </template>
        <template v-else>
          <p v-if="!granted" class="text-xs leading-5">请登录并解锁 Windows 桌面，再检查连接。</p>
          <p v-if="status.permission?.elevated" class="text-xs text-destructive">当前 helper 已在高权限运行；推荐以普通权限运行客户端。</p>
          <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">检查交互桌面</Button>
        </template>
        <Button v-if="!status.allowActions" size="sm" variant="outline" :disabled="locked" @click="toggle(true)">启用控制动作（保留本机审批）</Button>
        <p v-if="loadingError || status.error" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ loadingError || status.error }}</p>
        <details class="border-t border-border pt-3 text-xs leading-5">
          <summary class="cursor-pointer text-muted-foreground">授权与连接帮助</summary>
          <div class="mt-3 space-y-3">
            <template v-if="status.platform === 'macos'">
              <p>权限页未列出应用时，用“+”及 ⌘⇧G 添加下方 helper。新版系统可能显示“设备控制与数据访问”。只授权本应用或 helper，不要授权终端或其他程序。</p>
              <div class="rounded-lg bg-secondary/50 p-3">
                <div class="mb-1 text-muted-foreground">授权 helper</div>
                <code class="block break-all">{{ status.helperPath }}</code>
                <Button class="mt-2" size="sm" variant="outline" :disabled="busy" @click="copyHelperPath">复制 helper 路径</Button>
              </div>
              <p>返回应用会重新检测；若未生效，停止并重启 Runtime。系统权限可随时撤销，需由你亲自开启。</p>
            </template>
            <p v-else>Windows 使用 UI Automation，无 macOS 式授权开关；不绕过 UAC、锁屏或高权限应用限制。</p>
            <p>启用允许网页 AI 请求读取和控制授权应用，仍按 Runtime 权限模式审批。不会申请屏幕录制、完全磁盘访问或自动提权。</p>
            <p>首次启用后，在网页 MCP 管理页刷新工具。Blender 等自绘界面仍需专用适配器。</p>
          </div>
        </details>
      </div>
    </template>
  </section>
</template>
