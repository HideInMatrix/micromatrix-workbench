<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Activity,
  ArrowRight,
  Bot,
  Boxes,
  CircleCheck,
  CircleDot,
  Link2,
  LockKeyhole,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  Workflow,
  Wrench,
} from '@lucide/vue'
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
  <section class="flex min-h-0 w-full flex-1 flex-col gap-5">
    <header class="flex items-start justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <Boxes :size="18" />
          <h1 class="m-0 text-xl font-medium tracking-[-0.02em]">Capability Workbench</h1>
        </div>
        <p class="mt-1 mb-0 max-w-3xl text-xs leading-[18px] text-muted-foreground">
          管理 AI 可发现、可选择、可执行的能力。宿主 AI 负责理解任务与做决策，Workbench 负责能力目录、执行边界、依赖关系与运行健康。
        </p>
      </div>
      <Button variant="outline" size="sm" :disabled="busy" @click="refresh">
        <RefreshCw :size="14" />刷新
      </Button>
    </header>

    <div v-if="error" class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
      {{ error }}
    </div>

    <div class="py-1">
      <div class="mb-3">
        <span class="font-mono text-[10px] font-semibold tracking-[0.16em] text-muted-foreground">AI CAPABILITY GATEWAY</span>
      </div>

      <div class="flex flex-nowrap items-center justify-center gap-3.5 max-[980px]:flex-col" aria-label="Capability Gateway 调用流程">
        <div class="flex w-[280px] min-w-[280px] max-w-[280px] items-center gap-3 rounded-[10px] border border-violet-500/35 bg-violet-500/10 px-4 py-3.5 shadow-[inset_0_1px_0_rgb(255_255_255/2%)] max-[980px]:w-[min(100%,360px)] max-[980px]:min-w-0 max-[980px]:max-w-[360px] max-[820px]:w-[min(100%,340px)] max-[820px]:max-w-[340px]">
          <div class="inline-flex size-[42px] flex-none items-center justify-center rounded-full border border-violet-500/35 bg-violet-500/12 text-violet-500"><Bot :size="20" /></div>
          <div class="min-w-0 flex-1 text-left">
            <strong class="block text-[13px] font-semibold">AI Client</strong>
            <span class="mt-0.5 block text-[10px] text-foreground/70">理解任务 / 做决策</span>
            <p class="mt-2 mb-0 max-w-[210px] text-[10px] leading-4 text-muted-foreground">读取能力目录，并根据当前任务自主选择最合适的 Capability。</p>
          </div>
        </div>
        <ArrowRight class="flex-none text-muted-foreground max-[980px]:rotate-90" :size="16" />
        <div class="flex w-[280px] min-w-[280px] max-w-[280px] items-center gap-3 rounded-[10px] border border-blue-500/35 bg-blue-500/10 px-4 py-3.5 shadow-[inset_0_1px_0_rgb(255_255_255/2%)] max-[980px]:w-[min(100%,360px)] max-[980px]:min-w-0 max-[980px]:max-w-[360px] max-[820px]:w-[min(100%,340px)] max-[820px]:max-w-[340px]">
          <div class="inline-flex size-[42px] flex-none items-center justify-center rounded-full border border-blue-500/35 bg-blue-500/12 text-blue-500"><Boxes :size="20" /></div>
          <div class="min-w-0 flex-1 text-left">
            <strong class="block text-[13px] font-semibold">Capability Catalog</strong>
            <span class="mt-0.5 block text-[10px] text-foreground/70">发现 / 健康 / 依赖</span>
            <p class="mt-2 mb-0 max-w-[210px] text-[10px] leading-4 text-muted-foreground">统一描述可用能力、运行状态、依赖关系与调用契约。</p>
          </div>
        </div>
        <ArrowRight class="flex-none text-muted-foreground max-[980px]:rotate-90" :size="16" />
        <div class="flex w-[280px] min-w-[280px] max-w-[280px] items-center gap-3 rounded-[10px] border border-green-500/35 bg-green-500/10 px-4 py-3.5 shadow-[inset_0_1px_0_rgb(255_255_255/2%)] max-[980px]:w-[min(100%,360px)] max-[980px]:min-w-0 max-[980px]:max-w-[360px] max-[820px]:w-[min(100%,340px)] max-[820px]:max-w-[340px]">
          <div class="inline-flex size-[42px] flex-none items-center justify-center rounded-full border border-green-500/35 bg-green-500/12 text-green-500"><ShieldCheck :size="20" /></div>
          <div class="min-w-0 flex-1 text-left">
            <strong class="block text-[13px] font-semibold">Secure Runtime</strong>
            <span class="mt-0.5 block text-[10px] text-foreground/70">权限 / 沙箱 / 执行</span>
            <p class="mt-2 mb-0 max-w-[210px] text-[10px] leading-4 text-muted-foreground">所有执行经过权限控制和沙箱隔离，保证能力调用可控、可追溯。</p>
          </div>
        </div>
      </div>
    </div>

    <div>
      <div class="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 class="m-0 text-sm font-medium">能力目录</h2>
          <p class="mt-1 mb-0 text-xs text-muted-foreground">AI 当前可以发现的四类 Capability。</p>
        </div>
        <span class="font-mono text-[10px] text-muted-foreground">
          {{ catalog?.capabilities.length ?? 0 }} total
        </span>
      </div>

      <div class="grid grid-cols-4 gap-3 max-[1180px]:grid-cols-2 max-[820px]:grid-cols-1">
        <div class="min-h-[190px] cursor-default rounded-[10px] border border-blue-500/30 bg-blue-500/10 p-4 text-left shadow-[inset_0_1px_0_rgb(255_255_255/2%)]">
          <div class="flex h-full min-w-0 flex-col text-left">
            <div class="flex items-center justify-start gap-2.5">
              <div class="inline-flex size-[38px] flex-none items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/15 text-blue-500"><Wrench :size="18" /></div>
              <strong class="font-mono text-2xl font-medium">{{ counts.builtin_tool }}</strong>
            </div>
            <div class="mt-3.5 text-sm font-semibold">Built-in Tools</div>
            <p class="mt-2.5 mb-0 text-[11px] leading-[18px] text-muted-foreground">Workbench 自带的原子执行能力，包括文件、Git、进程与系统操作。</p>
          </div>
        </div>

        <button type="button" class="min-h-[190px] justify-start rounded-[10px] border border-violet-500/35 bg-violet-500/10 p-4 text-left shadow-[inset_0_1px_0_rgb(255_255_255/2%)] transition-[transform,filter] duration-150 hover:-translate-y-px hover:brightness-105" @click="router.push({ name: 'workbench-skills' })">
          <div class="flex h-full min-w-0 flex-col text-left justify-between">
            <div class="flex items-center justify-start gap-2.5">
              <div class="inline-flex size-[38px] flex-none items-center justify-center rounded-lg border border-violet-500/30 bg-violet-500/15 text-violet-500"><Sparkles :size="18" /></div>
              <strong class="font-mono text-2xl font-medium">{{ counts.skill }}</strong>
            </div>
            <div class="mt-3.5 text-sm font-semibold">Skills</div>
            <p class="mt-2.5 mb-0 text-[11px] leading-[18px] text-muted-foreground">给 AI 提供方法、知识、约束和产物约定。</p>
            <div class="mt-[22px] flex min-h-[38px] items-center justify-start gap-1 rounded-[7px] border border-violet-500/30 bg-violet-500/5 px-3 text-[11px] font-medium text-violet-400">管理 Skills <ArrowRight :size="13" /></div>
          </div>
        </button>

        <button type="button" class="min-h-[190px] justify-start rounded-[10px] border border-teal-500/35 bg-teal-500/10 p-4 text-left shadow-[inset_0_1px_0_rgb(255_255_255/2%)] transition-[transform,filter] duration-150 hover:-translate-y-px hover:brightness-105" @click="router.push({ name: 'workbench-mcp-connections' })">
          <div class="flex h-full min-w-0 flex-col text-left justify-between">
            <div class="flex items-center justify-start gap-2.5">
              <div class="inline-flex size-[38px] flex-none items-center justify-center rounded-lg border border-teal-500/30 bg-teal-500/15 text-teal-500"><Server :size="18" /></div>
              <strong class="font-mono text-2xl font-medium">{{ counts.mcp_tool }}</strong>
            </div>
            <div class="mt-3.5 text-sm font-semibold">External MCP</div>
            <p class="mt-2.5 mb-0 text-[11px] leading-[18px] text-muted-foreground">连接外部 MCP Server，把远端 Tool 纳入目录。</p>
            <div class="mt-[22px] flex min-h-[38px] items-center justify-start gap-1 rounded-[7px] border border-teal-500/30 bg-teal-500/5 px-3 text-[11px] font-medium text-teal-400">管理连接 <ArrowRight :size="13" /></div>
          </div>
        </button>

        <button type="button" class="min-h-[190px] justify-start rounded-[10px] border border-amber-500/35 bg-amber-500/10 p-4 text-left shadow-[inset_0_1px_0_rgb(255_255_255/2%)] transition-[transform,filter] duration-150 hover:-translate-y-px hover:brightness-105" @click="router.push({ name: 'workbench-workflows' })">
          <div class="flex h-full min-w-0 flex-col text-left justify-between">
            <div class="flex items-center justify-start gap-2.5">
              <div class="inline-flex size-[38px] flex-none items-center justify-center rounded-lg border border-amber-500/30 bg-amber-500/15 text-amber-500"><Workflow :size="18" /></div>
              <strong class="font-mono text-2xl font-medium">{{ counts.workflow }}</strong>
            </div>
            <div class="mt-3.5 text-sm font-semibold">Workflows</div>
            <p class="mt-2.5 mb-0 text-[11px] leading-[18px] text-muted-foreground">把已有 Capability 组成可重复执行的确定性流程。</p>
            <div class="mt-[22px] flex min-h-[38px] items-center justify-start gap-1 rounded-[7px] border border-amber-500/30 bg-amber-500/5 px-3 text-[11px] font-medium text-amber-400">编辑 Workflows <ArrowRight :size="13" /></div>
          </div>
        </button>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3 max-[820px]:grid-cols-1">
      <div class="min-h-[150px] rounded-[10px] border border-green-500/30 bg-green-500/10 p-4 shadow-[inset_0_1px_0_rgb(255_255_255/2%)]">
        <div class="flex items-center gap-[7px] text-xs font-semibold text-foreground"><Activity :size="15" />运行健康</div>
        <div class="mt-4 grid grid-cols-3 gap-2">
          <div class="flex min-h-[72px] flex-col items-start justify-center gap-0.5 rounded-[7px] border border-green-500/20 bg-green-500/5 px-3 text-left">
            <strong class="font-mono text-[22px] font-medium text-green-500">{{ availabilityCounts.available }}</strong>
            <span class="text-[10px] text-muted-foreground">Available</span>
            <small class="text-[9px] text-muted-foreground">可用</small>
          </div>
          <div class="flex min-h-[72px] flex-col items-start justify-center gap-0.5 rounded-[7px] border border-amber-500/20 bg-amber-500/5 px-3 text-left">
            <strong class="font-mono text-[22px] font-medium text-amber-500">{{ availabilityCounts.degraded }}</strong>
            <span class="text-[10px] text-muted-foreground">Degraded</span>
            <small class="text-[9px] text-muted-foreground">降级</small>
          </div>
          <div class="flex min-h-[72px] flex-col items-start justify-center gap-0.5 rounded-[7px] border border-red-500/20 bg-red-500/5 px-3 text-left">
            <strong class="font-mono text-[22px] font-medium text-red-500">{{ availabilityCounts.unavailable }}</strong>
            <span class="text-[10px] text-muted-foreground">Unavailable</span>
            <small class="text-[9px] text-muted-foreground">不可用</small>
          </div>
        </div>
      </div>

      <div class="min-h-[150px] rounded-[10px] border border-sky-500/30 bg-sky-500/10 p-4 shadow-[inset_0_1px_0_rgb(255_255_255/2%)]">
        <div class="flex items-center gap-[7px] text-xs font-semibold text-foreground"><Link2 :size="15" />依赖关系</div>
        <div class="mt-4 grid gap-2">
          <div class="flex min-h-[30px] items-center gap-2 rounded-md bg-background/30 px-2 text-[10px] text-muted-foreground">
            <CircleDot class="flex-none text-sky-400" :size="14" />
            <span><strong class="font-semibold text-foreground">{{ requiredDependencyCount }}</strong> 条必需依赖</span>
          </div>
          <div class="flex min-h-[30px] items-center gap-2 rounded-md bg-background/30 px-2 text-[10px] text-muted-foreground">
            <LockKeyhole class="flex-none text-sky-400" :size="14" />
            <span><strong class="font-semibold text-foreground">{{ protectedCapabilityCount }}</strong> 个能力受依赖保护</span>
          </div>
          <div v-if="unresolvedReferenceCount > 0" class="flex min-h-[30px] items-center gap-2 rounded-md bg-background/30 px-2 text-[10px] text-destructive">
            <CircleDot class="flex-none text-destructive" :size="14" />
            <span><strong class="font-semibold text-destructive">{{ unresolvedReferenceCount }}</strong> 个推荐引用不可用</span>
          </div>
          <div v-else class="flex min-h-[30px] items-center gap-2 rounded-md bg-background/30 px-2 text-[10px] text-muted-foreground">
            <CircleCheck class="flex-none text-green-500" :size="14" />
            <span>推荐引用状态正常</span>
          </div>
        </div>
      </div>

    </div>

    <div class="flex min-h-[38px] items-center justify-center gap-2.5 border-t border-border pt-1 text-[9px] text-muted-foreground max-[820px]:flex-wrap">
      <ShieldCheck class="text-slate-500" :size="14" />
      <span>所有能力执行均受权限控制与沙箱保护，操作可追溯</span>
      <i class="h-3 w-px bg-border"></i>
      <span>MicroMatrix Workbench</span>
      <i class="h-3 w-px bg-border"></i>
      <span>AI Capability Gateway</span>
    </div>
  </section>
</template>
