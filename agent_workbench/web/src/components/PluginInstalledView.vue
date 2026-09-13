<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, Plus, Search, Server, Settings2, Sparkles } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../api/desktop'
import type { CapabilityCatalogDto, MCPConnectionSummaryDto } from '../types'

type Tab = 'plugins' | 'mcp' | 'skills'
type InstalledItem = {
  key: string
  kind: 'mcp' | 'skill'
  name: string
  description: string
  id: string
}

const route = useRoute()
const router = useRouter()
const tabs: Array<{ id: Tab; label: string }> = [
  { id: 'plugins', label: '插件' },
  { id: 'mcp', label: 'MCP' },
  { id: 'skills', label: '技能' },
]
const catalog = ref<CapabilityCatalogDto | null>(null)
const initialTab = String(route.query.tab || '')
const activeTab = ref<Tab>(tabs.some(item => item.id === initialTab) ? initialTab as Tab : 'plugins')
const query = ref('')
const busy = ref(false)
const togglingId = ref('')
const error = ref('')
const addMenuOpen = ref(false)

const mcpItems = computed<InstalledItem[]>(() => (catalog.value?.mcp_connections ?? [])
  .map(item => ({
    key: `mcp:${item.id}`,
    kind: 'mcp',
    name: item.name,
    description: item.transport === 'http' ? item.endpoint : item.command,
    id: item.id,
  })))

const skillItems = computed<InstalledItem[]>(() => (catalog.value?.skills ?? [])
  .filter(item => item.scope !== 'built-in')
  .map(item => ({ key: `skill:${item.id}`, kind: 'skill', name: item.name, description: item.description, id: item.id })))

const allItems = computed(() => [...mcpItems.value, ...skillItems.value])
const tabItems = computed(() => activeTab.value === 'mcp'
    ? mcpItems.value
    : activeTab.value === 'skills'
      ? skillItems.value
      : allItems.value)
const filteredItems = computed(() => {
  const normalized = query.value.trim().toLowerCase()
  return normalized
    ? tabItems.value.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(normalized))
    : tabItems.value
})

const counts = computed(() => ({
  plugins: allItems.value.length,
  mcp: mcpItems.value.length,
  skills: skillItems.value.length,
}))

function connection(id: string) {
  return catalog.value?.mcp_connections.find(item => item.id === id)
}

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

async function toggleConnection(summary: MCPConnectionSummaryDto, enabled: boolean) {
  if (togglingId.value) return
  togglingId.value = summary.id
  error.value = ''
  try {
    const definition = await desktopApi.workbenchMCPConnection(summary.id)
    await desktopApi.saveWorkbenchMCPConnection({ ...definition, enabled }, definition.version)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    togglingId.value = ''
  }
}

function handleConnectionToggle(id: string, enabled: boolean) {
  const summary = connection(id)
  if (summary) void toggleConnection(summary, enabled)
}

function openItem(item: InstalledItem) {
  if (item.kind === 'mcp') {
    router.push({ name: 'plugins-mcp-detail', params: { connectionId: item.id } })
  } else if (item.kind === 'skill') {
    router.push({ name: 'plugins-skills-manage', query: { skill: item.id } })
  }
}

onMounted(refresh)
</script>

<template>
  <section class="flex w-full max-w-[790px] flex-1 flex-col px-4 pt-7 pb-12">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="m-0 text-2xl font-semibold tracking-[-0.03em]">插件</h1>
        <p class="mt-1 mb-0 text-xs text-muted-foreground">管理插件、技能和 MCP</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled title="线上插件目录暂未开放">浏览目录</Button>
        <div class="relative">
          <Button size="sm" @click="addMenuOpen = !addMenuOpen">添加<ChevronDown :size="13" /></Button>
          <div v-if="addMenuOpen" class="absolute right-0 top-[calc(100%+6px)] z-30 w-44 rounded-lg border border-border bg-popover p-1 shadow-lg">
            <button type="button" class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="router.push({ name: 'plugins-skills-manage' }); addMenuOpen = false">
              <Sparkles :size="14" />创建技能
            </button>
            <button type="button" class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs hover:bg-secondary" @click="router.push({ name: 'plugins-mcp-manage' }); addMenuOpen = false">
              <Plus :size="14" />添加 MCP 服务器
            </button>
          </div>
        </div>
      </div>
    </header>

    <div class="mt-7 flex items-center justify-between gap-5 border-b border-border">
      <div class="flex items-center gap-1">
        <button v-for="tab in tabs" :key="tab.id" type="button" :class="['relative px-2.5 py-2.5 text-xs', activeTab === tab.id ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground']" @click="activeTab = tab.id">
          {{ tab.label }} <span class="ml-0.5 text-[10px] text-muted-foreground">{{ counts[tab.id] }}</span>
          <span v-if="activeTab === tab.id" class="absolute right-1.5 bottom-[-1px] left-1.5 h-0.5 rounded-full bg-foreground" />
        </button>
      </div>
      <div class="relative w-[210px] pb-2">
        <Search class="pointer-events-none absolute top-[9px] left-2.5 text-muted-foreground" :size="14" />
        <input v-model="query" class="h-8 w-full rounded-xl border border-border bg-background pr-2.5 pl-8 text-xs outline-none focus:ring-2 focus:ring-ring/30" placeholder="搜索插件" />
      </div>
    </div>

    <div v-if="error" class="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{{ error }}</div>

    <template v-if="activeTab === 'mcp'">
      <section class="mt-6">
        <h2 class="mb-3 text-xs font-medium">服务器</h2>
        <div class="overflow-hidden rounded-xl border border-border bg-card">
          <div v-for="item in filteredItems" :key="item.key" class="flex min-h-12 items-center gap-3 border-b border-border px-3 last:border-b-0">
            <button type="button" class="flex min-w-0 flex-1 items-center gap-3 text-left" @click="openItem(item)">
              <div class="grid size-8 flex-none place-items-center rounded-lg border border-border bg-background"><Server :size="15" /></div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-xs font-medium">{{ item.name }}</div>
                <div class="mt-0.5 truncate text-[10px] text-muted-foreground">{{ item.description || 'MCP Server' }}</div>
              </div>
            </button>
            <button type="button" class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" title="设置" @click="router.push({ name: 'plugins-mcp-manage', query: { connection: item.id } })"><Settings2 :size="14" /></button>
            <div @click.stop>
              <Switch :model-value="Boolean(connection(item.id)?.enabled)" :disabled="Boolean(togglingId)" :aria-label="`${connection(item.id)?.enabled ? '停用' : '启用'} ${item.name}`" @update:model-value="value => handleConnectionToggle(item.id, value)" />
            </div>
          </div>
          <div v-if="!filteredItems.length" class="px-4 py-8 text-center text-xs text-muted-foreground">暂无 MCP 服务器</div>
        </div>
      </section>

      <section class="mt-7">
        <h2 class="mb-3 text-xs font-medium">来自插件</h2>
        <div class="rounded-xl border border-border px-4 py-5 text-xs text-muted-foreground">暂无来自线上插件的 MCP。插件目录暂未开放。</div>
      </section>
    </template>

    <div v-else class="mt-5 divide-y divide-border">
      <div v-for="item in filteredItems" :key="item.key" class="flex min-h-[54px] items-center gap-3 px-1">
        <button type="button" class="flex min-w-0 flex-1 items-center justify-start gap-3 text-left" @click="openItem(item)">
          <div class="grid size-9 flex-none place-items-center rounded-xl border border-border bg-card shadow-sm">
            <Server v-if="item.kind === 'mcp'" :size="17" />
            <Sparkles v-else :size="17" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-xs font-medium">{{ item.name }}</div>
            <div class="mt-0.5 truncate text-[10px] text-muted-foreground">{{ item.description }}</div>
          </div>
        </button>
        <template v-if="item.kind === 'mcp'">
          <div @click.stop>
            <Switch :model-value="Boolean(connection(item.id)?.enabled)" :disabled="Boolean(togglingId)" @update:model-value="value => handleConnectionToggle(item.id, value)" />
          </div>
        </template>
        <span v-else class="rounded-full bg-secondary px-2 py-1 text-[9px] text-muted-foreground">已安装</span>
      </div>
      <div v-if="!filteredItems.length" class="py-12 text-center text-xs text-muted-foreground">没有匹配的已安装项目</div>
    </div>
  </section>
</template>
