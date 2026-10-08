<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../../api/desktop'
import { updateInstallationLocked } from '../../composables/useAppUpdater'
import type { ComputerUseStatusDto } from '../../types'

const props = defineProps<{ locked?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const status = ref<ComputerUseStatusDto | null>(null)
const busy = ref(false)
const loadingError = ref('')
const browserEndpoint = ref('')
const browserOrigins = ref('')
const browserDirty = ref(false)
const browserError = ref('')
function loadBrowser() {
  if (browserDirty.value) return
  browserEndpoint.value = status.value?.browser?.endpoint ?? ''
  browserOrigins.value = status.value?.browser?.allowedOrigins.join('\n') ?? ''
}
const granted = computed(() => status.value?.platform === 'macos'
  ? status.value.permission?.accessibility === true : status.value?.permission?.interactiveDesktop === true)
const locked = computed(() => busy.value || props.locked || status.value?.running || updateInstallationLocked.value)
const permissionLabel = computed(() => !status.value?.enabled ? '未启用'
  : loadingError.value || status.value.error ? '检测失败'
  : !status.value.permission ? '尚未检查'
  : status.value.platform === 'windows' && status.value.permission.elevated ? '请使用普通权限'
  : granted.value ? (status.value.platform === 'macos' && status.value.permission?.screenRecording === false ? '截图未授权' : '权限就绪') : status.value.platform === 'macos' ? '需要系统授权' : '需要解锁交互桌面')

async function refresh() {
  status.value = await desktopApi.computerUseStatus()
  loadingError.value = ''
  loadBrowser()
}
async function check(request = false) {
  status.value = await desktopApi.checkComputerUsePermissions(request)
  loadingError.value = ''
  loadBrowser()
}
async function action(work: () => Promise<void>, browser = false) {
  if (busy.value || updateInstallationLocked.value) return
  busy.value = true
  try { await work() }
  catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (browser) browserError.value = message
    else loadingError.value = message
    toast.error(message)
  }
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
async function saveBrowser(clear = false) {
  if (locked.value) return
  await action(async () => {
    browserError.value = ''
    const endpoint = browserEndpoint.value.trim()
    const allowedOrigins = [...new Set(browserOrigins.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean))]
    if (!clear && (!endpoint || !allowedOrigins.length)) throw new Error('填写本地连接地址和至少一个允许的网站')
    status.value = await desktopApi.configureComputerUseBrowser(clear ? null : {endpoint, allowedOrigins})
    browserDirty.value = false
    loadBrowser()
    emit('changed')
    toast.success(clear ? '已关闭浏览器通道' : '浏览器配置已保存')
  }, true)
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
          <Button v-if="!granted || status.permission?.screenRecording === false" size="sm" :variant="granted ? 'outline' : 'default'" :disabled="busy || !status.allowActions || updateInstallationLocked" @click="requestPermission">设置权限</Button>
          <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测</Button>
        </div>
      </template>
      <template v-else>
        <Button size="sm" variant="outline" :disabled="busy || updateInstallationLocked" @click="action(() => check(false))">重新检测</Button>
      </template>
      <Button v-if="!status.allowActions" size="sm" variant="outline" :disabled="locked" @click="toggle(true)">启用控制动作（保留本机审批）</Button>
      <p v-if="loadingError || status.error" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ loadingError || status.error }}</p>
    </div>
    <!-- Browser configuration is platform-independent; native support still gates desktop activation above. -->
    <details v-if="status" class="mt-4 border-t border-border pt-3">
      <summary class="cursor-pointer text-sm">浏览器连接<span v-if="status.browser" class="ml-2 text-xs text-muted-foreground">已配置</span></summary>
      <fieldset :disabled="locked" class="mt-3 space-y-3">
        <FormField label="本地浏览器连接地址">
          <input id="computer-browser-endpoint" aria-label="本地浏览器连接地址" v-model="browserEndpoint" placeholder="ws://127.0.0.1:9222/devtools/browser/…" @input="browserDirty = true" />
        </FormField>
        <FormField label="允许的网站（每行一个）">
          <textarea id="computer-browser-origins" aria-label="允许的网站" v-model="browserOrigins" :rows="3" placeholder="https://example.com" @input="browserDirty = true" />
        </FormField>
        <p class="text-xs text-muted-foreground">仅连接已开启调试的独立 Chromium 浏览器；保存不启动浏览器或 Runtime。</p>
        <p v-if="browserError" role="alert" aria-label="浏览器配置错误" class="whitespace-pre-wrap text-xs text-destructive">{{ browserError }}</p>
        <div class="flex gap-2">
          <Button size="sm" :disabled="locked || !browserDirty" @click="saveBrowser()">保存</Button>
          <Button size="sm" variant="outline" :disabled="locked || !status?.browser" @click="saveBrowser(true)">关闭通道</Button>
        </div>
      </fieldset>
    </details>
  </section>
</template>
