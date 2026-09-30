<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Box, RefreshCw, Search, Wrench } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../api/desktop'
import type { BodyPluginDto, CapabilityCatalogDto } from '../types'

const plugins = ref<BodyPluginDto[]>([])
const catalog = ref<CapabilityCatalogDto | null>(null)
const query = ref('')
const busy = ref(false)
const togglingId = ref('')

const capabilities = computed(() => {
  const normalized = query.value.trim().toLowerCase()
  const values = catalog.value?.capabilities ?? []
  return normalized
    ? values.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(normalized))
    : values
})

async function refresh() {
  busy.value = true
  try {
    const [bodyPlugins, capabilityCatalog] = await Promise.all([
      desktopApi.listBodyPlugins(),
      desktopApi.capabilityCatalog(),
    ])
    plugins.value = bodyPlugins
    catalog.value = capabilityCatalog
  } catch (reason) {
    toast.error(reason instanceof Error ? reason.message : String(reason), { id: 'plugins-refresh' })
  } finally {
    busy.value = false
  }
}

async function togglePlugin(plugin: BodyPluginDto, enabled: boolean) {
  if (plugin.required || togglingId.value) return
  togglingId.value = plugin.id
  try {
    await desktopApi.setBodyPluginEnabled(plugin.id, enabled)
    await refresh()
    toast.success(`${plugin.name} 已${enabled ? '启用' : '停用'}。`)
  } catch (reason) {
    toast.error(reason instanceof Error ? reason.message : String(reason))
  } finally {
    togglingId.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <section class="flex w-full max-w-[840px] flex-1 flex-col px-4 pt-7 pb-12">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="m-0 text-2xl font-semibold tracking-[-0.03em]">Pi 插件</h1>
        <p class="mt-1 mb-0 text-xs text-muted-foreground">控制本地执行身体加载的插件，并查看当前暴露给 MCP 客户端的工具。</p>
      </div>
      <Button variant="ghost" size="icon" class="h-8 w-8" :disabled="busy" title="刷新" @click="refresh">
        <RefreshCw :size="15" />
      </Button>
    </header>

    <section class="mt-7">
      <h2 class="mb-3 text-sm font-medium">执行插件</h2>
      <div class="overflow-hidden rounded-xl border border-border bg-card">
        <div v-for="plugin in plugins" :key="plugin.id" class="flex min-h-14 items-center gap-3 border-b border-border px-4 last:border-b-0">
          <div class="grid size-8 flex-none place-items-center rounded-lg border border-border bg-background"><Box :size="15" /></div>
          <div class="min-w-0 flex-1">
            <div class="text-xs font-medium">{{ plugin.name }}</div>
            <div class="mt-0.5 text-[10px] text-muted-foreground">{{ plugin.id }}{{ plugin.required ? ' · Runtime 必需' : '' }}</div>
          </div>
          <Switch
            :model-value="plugin.enabled"
            :disabled="plugin.required || Boolean(togglingId)"
            :aria-label="`${plugin.enabled ? '停用' : '启用'} ${plugin.name}`"
            @update:model-value="value => togglePlugin(plugin, value)"
          />
        </div>
        <div v-if="!plugins.length && !busy" class="px-4 py-8 text-center text-xs text-muted-foreground">没有已注册插件</div>
      </div>
      <p class="mt-2 text-[10px] leading-4 text-muted-foreground">运行中的 Runtime 会锁定插件配置；先停止服务，再修改插件开关。</p>
    </section>

    <section class="mt-8">
      <div class="flex items-center justify-between gap-4">
        <h2 class="m-0 text-sm font-medium">当前 MCP 工具</h2>
        <div class="relative w-[240px]">
          <Search class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground" :size="14" />
          <input v-model="query" class="h-8 w-full rounded-xl border border-border bg-background pr-3 pl-8 text-xs outline-none focus:ring-2 focus:ring-ring/30" placeholder="搜索工具" />
        </div>
      </div>
      <div class="mt-3 divide-y divide-border rounded-xl border border-border bg-card">
        <div v-for="item in capabilities" :key="item.id" class="flex min-h-14 items-center gap-3 px-4">
          <div class="grid size-8 flex-none place-items-center rounded-lg border border-border bg-background"><Wrench :size="14" /></div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-xs font-medium">{{ item.name }}</div>
            <div class="mt-0.5 line-clamp-2 text-[10px] text-muted-foreground">{{ item.description }}</div>
          </div>
          <span class="rounded-full bg-secondary px-2 py-1 text-[9px] text-muted-foreground">{{ item.source.plugin_id || 'system' }}</span>
        </div>
        <div v-if="!capabilities.length && !busy" class="px-4 py-8 text-center text-xs text-muted-foreground">没有匹配的工具</div>
      </div>
    </section>
  </section>
</template>
