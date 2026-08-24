<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Boxes, RefreshCw, Server, Sparkles, Workflow, Wrench } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { desktopApi } from '../api/desktop'
import type { CapabilityCatalogDto, CapabilityDto } from '../types'

const router = useRouter()
const catalog = ref<CapabilityCatalogDto | null>(null)
const busy = ref(false)
const error = ref('')

const counts = computed(() => {
  const values = catalog.value?.capabilities ?? []
  return values.reduce<Record<CapabilityDto['type'], number>>(
    (result, item) => {
      result[item.type] += 1
      return result
    },
    { builtin_tool: 0, skill: 0, mcp_tool: 0, workflow: 0 },
  )
})

const unresolvedReferenceCount = computed(() => (
  (catalog.value?.capabilities ?? []).reduce((count, item) => (
    count + (item.recommended_capability_status?.unresolved.length ?? 0)
  ), 0)
))

const requiredDependencyCount = computed(() => (
  (catalog.value?.capabilities ?? []).reduce((count, item) => (
    count + (item.dependencies?.filter(dependency => dependency.required).length ?? 0)
  ), 0)
))

const protectedCapabilityCount = computed(() => (
  (catalog.value?.capabilities ?? []).filter(item => (
    item.dependents?.some(dependent => dependent.required)
  )).length
))

const availabilityCounts = computed(() => {
  const result = { available: 0, degraded: 0, unavailable: 0 }
  for (const item of catalog.value?.capabilities ?? []) {
    result[item.availability?.status ?? 'available'] += 1
  }
  return result
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

onMounted(refresh)
</script>

<template>
  <section class="flex min-h-0 w-full flex-1 flex-col gap-4">
    <header class="flex items-start justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <Boxes :size="18" />
          <h1 class="m-0 text-xl font-medium tracking-[-0.02em]">Capability Workbench</h1>
        </div>
        <p class="mt-1 mb-0 max-w-3xl text-xs leading-[18px] text-muted-foreground">
          Workbench 负责向宿主 AI 暴露和执行能力，不负责替 AI 理解用户意图。Built-in Tool、Skill、External MCP Tool 与 Workflow 都是可被 AI 自主选择的 Capability。
        </p>
      </div>
      <Button variant="outline" size="sm" :disabled="busy" @click="refresh">
        <RefreshCw :size="14" />刷新
      </Button>
    </header>

    <div v-if="error" class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
      {{ error }}
    </div>

    <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <button type="button" class="capability-card" @click="router.push({ name: 'workbench-workflows' })">
        <Workflow :size="18" />
        <div>
          <div class="text-sm font-medium">Workflows</div>
          <div class="mt-1 text-xs text-muted-foreground">确定性编排已有能力，由 AI 决定何时启动。</div>
        </div>
      </button>

      <button type="button" class="capability-card" @click="router.push({ name: 'workbench-skills' })">
        <Sparkles :size="18" />
        <div>
          <div class="flex items-center gap-2 text-sm font-medium">
            Skills
            <span class="font-mono text-[10px] text-muted-foreground">{{ counts.skill }}</span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground">向 AI 提供方法、约束、知识与产物约定。</div>
        </div>
      </button>

      <button type="button" class="capability-card" @click="router.push({ name: 'workbench-mcp-connections' })">
        <Server :size="18" />
        <div>
          <div class="flex items-center gap-2 text-sm font-medium">
            External MCP
            <span class="font-mono text-[10px] text-muted-foreground">{{ counts.mcp_tool }}</span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground">连接其他 MCP Server，把外部 Tool 纳入能力目录。</div>
        </div>
      </button>

      <div class="capability-card cursor-default">
        <Wrench :size="18" />
        <div>
          <div class="flex items-center gap-2 text-sm font-medium">
            Built-in Tools
            <span class="font-mono text-[10px] text-muted-foreground">{{ counts.builtin_tool }}</span>
          </div>
          <div class="mt-1 text-xs text-muted-foreground">文件、Git、进程、系统与安全运行时提供的原子动作。</div>
        </div>
      </div>
    </div>

    <div class="rounded-lg border border-border bg-card p-4">
      <h2 class="m-0 text-sm font-medium">调用关系</h2>
      <div class="mt-3 grid gap-2 font-mono text-xs text-muted-foreground">
        <div>AI Client → MCP → Capability Catalog</div>
        <div>AI Client → 选择 Capability → Tool / Skill / External MCP / Workflow</div>
        <div>Capability → Permission / Sandbox / Runtime → Workspace</div>
      </div>
      <p class="mt-3 mb-0 text-xs leading-[18px] text-muted-foreground">
        Capability Catalog 只负责描述“有什么能力、怎样调用”，不会进行关键词匹配、任务打分或自动路由。
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3 text-[10px] text-muted-foreground">
        <span>Catalog revision: <span class="font-mono">{{ catalog?.revision || '—' }}</span></span>
        <span>{{ availabilityCounts.available }} available</span>
        <span v-if="availabilityCounts.degraded > 0">{{ availabilityCounts.degraded }} degraded</span>
        <span v-if="availabilityCounts.unavailable > 0" class="text-destructive">
          {{ availabilityCounts.unavailable }} unavailable
        </span>
        <span>{{ requiredDependencyCount }} 条必需依赖</span>
        <span>{{ protectedCapabilityCount }} 个 Capability 受依赖保护</span>
        <span v-if="unresolvedReferenceCount > 0" class="text-destructive">
          {{ unresolvedReferenceCount }} 个推荐 Capability 引用当前不可用
        </span>
        <span v-else>Capability 引用状态正常</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.capability-card {
  display: flex;
  min-height: 116px;
  align-items: flex-start;
  gap: 12px;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  background: hsl(var(--card));
  padding: 16px;
  text-align: left;
  transition: background-color 120ms ease, border-color 120ms ease;
}

button.capability-card:hover {
  background: hsl(var(--secondary));
}
</style>
