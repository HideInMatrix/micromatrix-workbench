<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Boxes, Plus, RefreshCw, Search, Server, Settings2, Sparkles } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Popover } from '@/components/ui/popover'
import { desktopApi } from '../api/desktop'
import type { CapabilityCatalogDto } from '../types'

const router = useRouter()
const catalog = ref<CapabilityCatalogDto | null>(null)
const query = ref('')
const busy = ref(false)
const error = ref('')

const installedItems = computed(() => {
  const values = [
    ...(catalog.value?.mcp_connections ?? []).map(item => ({
      key: `mcp:${item.id}`,
      type: 'mcp' as const,
      name: item.name,
      description: item.transport === 'http' ? item.endpoint : item.command,
    })),
    ...(catalog.value?.skills ?? [])
      .filter(item => item.scope !== 'built-in')
      .map(item => ({
        key: `skill:${item.id}`,
        type: 'skill' as const,
        name: item.name,
        description: item.description,
      })),
  ]
  const normalized = query.value.trim().toLowerCase()
  return normalized
    ? values.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(normalized))
    : values
})

async function refresh() {
  busy.value = true
  error.value = ''
  try {
    catalog.value = await desktopApi.capabilityCatalog()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}

function openInstalled(type?: 'plugins' | 'mcp' | 'skills') {
  if (type) {
    router.push({ name: 'plugins-installed', query: { tab: type } })
    return
  }
  router.push({ name: 'plugins-installed' })
}

onMounted(refresh)
</script>

<template>
  <section class="flex w-full max-w-[760px] flex-1 flex-col px-4 pt-7 pb-12">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="m-0 text-2xl font-semibold tracking-[-0.03em]">插件</h1>
        <p class="mt-1 mb-0 text-xs text-muted-foreground">管理已安装的插件、技能和 MCP</p>
      </div>
      <div class="flex items-center gap-1.5">
        <Button variant="ghost" size="icon" class="h-8 w-8" :disabled="busy" title="刷新" @click="refresh">
          <RefreshCw :size="15" />
        </Button>
        <Popover content-class="w-40 p-1">
          <template #trigger>
            <Button size="sm" class="gap-1.5">
              <Plus :size="14" />添加
            </Button>
          </template>
          <button type="button" class="flex w-full items-center justify-start gap-2 rounded-md px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="router.push({ name: 'plugins-skills-manage' })">
            <Sparkles :size="14" />创建技能
          </button>
          <button type="button" class="flex w-full items-center justify-start gap-2 rounded-md px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="router.push({ name: 'plugins-mcp-manage' })">
            <Server :size="14" />添加 MCP 服务器
          </button>
        </Popover>
      </div>
    </header>

    <div class="relative mt-7">
      <Search class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground" :size="15" />
      <input
        v-model="query"
        class="h-9 w-full rounded-xl border border-border bg-background pr-3 pl-9 text-xs outline-none transition-shadow placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/30"
        placeholder="搜索插件"
      />
    </div>

    <div v-if="error" class="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{{ error }}</div>

    <section class="mt-7">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="m-0 text-sm font-medium">已安装</h2>
        <button type="button" class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" title="管理已安装插件" @click="openInstalled()"><Settings2 :size="14" /></button>
      </div>

      <button
        v-if="installedItems.length"
        type="button"
        class="flex w-full flex-wrap items-start justify-start gap-4 rounded-xl border-0 bg-transparent p-0 text-left"
        aria-label="查看已安装插件"
        @click="openInstalled()"
      >
        <div v-for="item in installedItems.slice(0, 12)" :key="item.key" class="group flex w-[64px] flex-col items-start gap-1.5">
          <div class="grid size-10 place-items-center rounded-xl border border-border bg-card shadow-sm transition-transform group-hover:-translate-y-0.5">
            <Server v-if="item.type === 'mcp'" :size="19" />
            <Sparkles v-else :size="19" />
          </div>
          <span class="w-full truncate text-left text-[9px] text-muted-foreground">{{ item.name }}</span>
        </div>
      </button>
      <button v-else type="button" class="flex min-h-28 w-full items-center justify-center rounded-xl border border-dashed border-border text-xs text-muted-foreground" @click="openInstalled()">
        <Boxes :size="16" class="mr-2" />暂无匹配的已安装项目
      </button>
    </section>

    <div class="mt-9 border-t border-border pt-5 text-[11px] leading-5 text-muted-foreground">
      在线插件目录暂未开放。当前页面只展示本机安装或创建的 Skills 和 MCP Connections，不展示内置能力、热门或推荐内容。
    </div>
  </section>
</template>
