<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, ChevronLeft, Copy, Ellipsis, PlugZap, RefreshCw, Server, Settings2, Trash2 } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { desktopApi } from '../api/desktop'
import type { MCPConnectionDefinitionDto } from '../types'

const route = useRoute()
const router = useRouter()
const connectionId = computed(() => String(route.params.connectionId || ''))
const connection = ref<MCPConnectionDefinitionDto | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const moreOpen = ref(false)
const statusOpen = ref(false)

const statusLabel = computed(() => {
  if (!connection.value?.enabled) return '已断开'
  if (connection.value.last_error) return '连接异常'
  return '已连接'
})

const statusDotClass = computed(() => !connection.value?.enabled
  ? 'bg-muted-foreground'
  : connection.value.last_error
    ? 'bg-amber-500'
    : 'bg-emerald-500')

const locationValue = computed(() => {
  if (!connection.value) return ''
  return connection.value.transport === 'http'
    ? connection.value.endpoint
    : [connection.value.command, ...(connection.value.arguments ?? [])].filter(Boolean).join(' ')
})

async function load() {
  busy.value = true
  error.value = ''
  try {
    connection.value = await desktopApi.workbenchMCPConnection(connectionId.value)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

async function saveEnabled(enabled: boolean) {
  if (!connection.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await desktopApi.saveWorkbenchMCPConnection(
      { ...connection.value, enabled },
      connection.value.version,
    )
    connection.value = result.connection
    notice.value = enabled ? 'MCP 已连接。' : 'MCP 已断开。'
    statusOpen.value = false
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

async function testConnection() {
  if (!connection.value) return
  if (!connection.value.enabled) {
    await saveEnabled(true)
    if (!connection.value?.enabled) return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await desktopApi.testWorkbenchMCPConnection(connection.value.id, 8, true)
    if (!result.ok) throw new Error(result.error || 'MCP 连接测试失败。')
    notice.value = `连接正常 · MCP ${result.protocol_version || '未知版本'} · ${result.elapsed_ms}ms`
    await load()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
    statusOpen.value = false
  }
}

async function copyLink() {
  const value = locationValue.value || connection.value?.id || ''
  try {
    await navigator.clipboard.writeText(value)
    notice.value = connection.value?.transport === 'http' ? 'MCP 地址已复制。' : 'MCP 启动信息已复制。'
  } catch {
    error.value = '当前 WebView 无法写入剪贴板。'
  }
}

async function uninstall() {
  if (!connection.value) return
  moreOpen.value = false
  if (!window.confirm(`卸载 MCP “${connection.value.name}”？此操作会删除本地 MCP Connection 配置。`)) return
  busy.value = true
  error.value = ''
  try {
    if (await desktopApi.deleteWorkbenchMCPConnection(connection.value.id)) {
      await router.replace({ name: 'plugins-installed', query: { tab: 'mcp' } })
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="mx-auto flex w-full max-w-[760px] flex-1 flex-col px-4 pt-3 pb-12">
    <button type="button" class="mb-6 flex w-fit items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground" @click="router.push({ name: 'plugins-installed', query: { tab: 'mcp' } })">
      <ChevronLeft :size="13" />插件 <span class="mx-1 text-border">/</span> {{ connection?.name || connectionId }}
    </button>

    <div v-if="error" class="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{{ error }}</div>
    <div v-if="notice" class="mb-4 rounded-lg border border-border bg-secondary/50 px-3 py-2 text-xs text-muted-foreground">{{ notice }}</div>

    <template v-if="connection">
      <header class="flex items-start justify-between gap-6">
        <div class="flex min-w-0 items-start gap-4">
          <div class="grid size-12 flex-none place-items-center rounded-2xl border border-border bg-card shadow-sm">
            <Server :size="22" />
          </div>
          <div class="min-w-0 pt-1">
            <div class="flex items-center gap-2">
              <h1 class="m-0 truncate text-xl font-semibold tracking-[-0.025em]">{{ connection.name }}</h1>
              <span class="rounded-full border border-border px-1.5 py-0.5 text-[9px] text-muted-foreground">MCP</span>
            </div>
            <p class="mt-1 mb-0 text-xs text-muted-foreground">{{ connection.id }}</p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <div class="relative">
            <Button variant="ghost" size="icon" class="h-8 w-8" title="更多" @click="moreOpen = !moreOpen"><Ellipsis :size="16" /></Button>
            <div v-if="moreOpen" class="absolute right-0 top-[calc(100%+6px)] z-30 w-36 rounded-xl border border-border bg-popover p-1.5 shadow-lg">
              <button type="button" class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-destructive hover:bg-destructive/10" @click="uninstall">
                <Trash2 :size="14" />卸载
              </button>
            </div>
          </div>
          <Button variant="outline" size="sm" :disabled="busy" @click="copyLink"><Copy :size="14" />复制链接</Button>
          <Button size="sm" :disabled="busy" @click="testConnection"><PlugZap :size="14" />立即试用</Button>
        </div>
      </header>

      <section class="mt-7">
        <h2 class="mb-3 text-sm font-medium">应用 <span class="ml-1 text-xs font-normal text-muted-foreground">1</span></h2>
        <div class="flex min-h-[58px] items-center gap-3 border-y border-border py-3">
          <div class="grid size-8 place-items-center rounded-lg border border-border bg-card"><Server :size="15" /></div>
          <div class="min-w-0 flex-1">
            <div class="text-xs font-medium">{{ connection.name }}</div>
            <div class="mt-0.5 truncate text-[10px] text-muted-foreground">{{ connection.tool_count }} 个已发现工具</div>
          </div>
          <Button variant="ghost" size="icon" class="h-8 w-8" title="编辑配置" @click="router.push({ name: 'plugins-mcp-manage', query: { connection: connection.id } })"><Settings2 :size="14" /></Button>
          <div class="relative">
            <button type="button" class="flex h-8 items-center gap-1.5 rounded-xl border border-border bg-background px-2.5 text-[11px] hover:bg-secondary" :disabled="busy" @click="statusOpen = !statusOpen">
              <span :class="['size-1.5 rounded-full', statusDotClass]" />{{ statusLabel }}<ChevronDown :size="12" />
            </button>
            <div v-if="statusOpen" class="absolute right-0 top-[calc(100%+6px)] z-20 w-36 rounded-xl border border-border bg-popover p-1.5 shadow-lg">
              <button v-if="connection.enabled" type="button" class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="testConnection"><RefreshCw :size="13" />重新连接</button>
              <button v-if="connection.enabled" type="button" class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs text-destructive hover:bg-destructive/10" @click="saveEnabled(false)">断开连接</button>
              <button v-else type="button" class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="saveEnabled(true)"><PlugZap :size="13" />连接</button>
            </div>
          </div>
        </div>
      </section>

      <section class="mt-7">
        <h2 class="mb-3 text-sm font-medium">信息</h2>
        <dl class="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-3 border-t border-border pt-4 text-xs">
          <dt class="text-muted-foreground">类别</dt><dd class="m-0">MCP</dd>
          <dt class="text-muted-foreground">传输方式</dt><dd class="m-0 uppercase">{{ connection.transport }}</dd>
          <dt class="text-muted-foreground">配置版本</dt><dd class="m-0">v{{ connection.version }}</dd>
          <dt class="text-muted-foreground">地址 / 命令</dt><dd class="m-0 break-all font-mono text-[11px]">{{ locationValue || '未配置' }}</dd>
          <dt class="text-muted-foreground">发现工具</dt><dd class="m-0">{{ connection.tool_count }}</dd>
        </dl>
      </section>

      <p class="mt-7 border-t border-border pt-4 text-[10px] leading-[17px] text-muted-foreground">
        连接此 MCP 后，它发现的工具会进入当前 Capability Catalog。HTTP 调用仍受 Network permission 约束，stdio 调用仍受外部可执行程序授权约束；插件页面不会扩大 Runtime 权限。
      </p>
    </template>

    <div v-else-if="busy" class="py-16 text-center text-xs text-muted-foreground">正在加载 MCP…</div>
  </section>
</template>
