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

    <div class="gateway-panel">
      <div class="gateway-eyebrow-row">
        <span class="gateway-eyebrow">AI CAPABILITY GATEWAY</span>
      </div>

      <div class="gateway-flow" aria-label="Capability Gateway 调用流程">
        <div class="gateway-node gateway-node-ai">
          <div class="gateway-node-icon"><Bot :size="20" /></div>
          <div class="gateway-node-copy">
            <strong>AI Client</strong>
            <span>理解任务 / 做决策</span>
            <p>读取能力目录，并根据当前任务自主选择最合适的 Capability。</p>
          </div>
        </div>
        <ArrowRight class="gateway-arrow" :size="16" />
        <div class="gateway-node gateway-node-catalog">
          <div class="gateway-node-icon"><Boxes :size="20" /></div>
          <div class="gateway-node-copy">
            <strong>Capability Catalog</strong>
            <span>发现 / 健康 / 依赖</span>
            <p>统一描述可用能力、运行状态、依赖关系与调用契约。</p>
          </div>
        </div>
        <ArrowRight class="gateway-arrow" :size="16" />
        <div class="gateway-node gateway-node-runtime">
          <div class="gateway-node-icon"><ShieldCheck :size="20" /></div>
          <div class="gateway-node-copy">
            <strong>Secure Runtime</strong>
            <span>权限 / 沙箱 / 执行</span>
            <p>所有执行经过权限控制和沙箱隔离，保证能力调用可控、可追溯。</p>
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

      <div class="capability-grid">
        <div class="capability-card capability-card-static capability-card-blue">
          <div class="capability-body">
            <div class="capability-topline">
              <div class="capability-icon"><Wrench :size="18" /></div>
              <strong>{{ counts.builtin_tool }}</strong>
            </div>
            <div class="capability-title">Built-in Tools</div>
            <p>Workbench 自带的原子执行能力，包括文件、Git、进程与系统操作。</p>
          </div>
        </div>

        <button type="button" class="capability-card capability-card-violet" @click="router.push({ name: 'workbench-skills' })">
          <div class="capability-body">
            <div class="capability-topline">
              <div class="capability-icon"><Sparkles :size="18" /></div>
              <strong>{{ counts.skill }}</strong>
            </div>
            <div class="capability-title">Skills</div>
            <p>给 AI 提供方法、知识、约束和产物约定。</p>
            <div class="capability-footer capability-link">管理 Skills <ArrowRight :size="13" /></div>
          </div>
        </button>

        <button type="button" class="capability-card capability-card-teal" @click="router.push({ name: 'workbench-mcp-connections' })">
          <div class="capability-body">
            <div class="capability-topline">
              <div class="capability-icon"><Server :size="18" /></div>
              <strong>{{ counts.mcp_tool }}</strong>
            </div>
            <div class="capability-title">External MCP</div>
            <p>连接外部 MCP Server，把远端 Tool 纳入目录。</p>
            <div class="capability-footer capability-link">管理连接 <ArrowRight :size="13" /></div>
          </div>
        </button>

        <button type="button" class="capability-card capability-card-amber" @click="router.push({ name: 'workbench-workflows' })">
          <div class="capability-body">
            <div class="capability-topline">
              <div class="capability-icon"><Workflow :size="18" /></div>
              <strong>{{ counts.workflow }}</strong>
            </div>
            <div class="capability-title">Workflows</div>
            <p>把已有 Capability 组成可重复执行的确定性流程。</p>
            <div class="capability-footer capability-link">编辑 Workflows <ArrowRight :size="13" /></div>
          </div>
        </button>
      </div>
    </div>

    <div class="status-grid">
      <div class="status-panel status-panel-green">
        <div class="status-panel-title"><Activity :size="15" />运行健康</div>
        <div class="status-metrics">
          <div class="health-metric health-available">
            <strong>{{ availabilityCounts.available }}</strong>
            <span>Available</span>
            <small>可用</small>
          </div>
          <div class="health-metric health-degraded">
            <strong>{{ availabilityCounts.degraded }}</strong>
            <span>Degraded</span>
            <small>降级</small>
          </div>
          <div class="health-metric health-unavailable">
            <strong>{{ availabilityCounts.unavailable }}</strong>
            <span>Unavailable</span>
            <small>不可用</small>
          </div>
        </div>
      </div>

      <div class="status-panel status-panel-sky">
        <div class="status-panel-title"><Link2 :size="15" />依赖关系</div>
        <div class="dependency-list">
          <div class="dependency-item">
            <CircleDot :size="14" />
            <span><strong>{{ requiredDependencyCount }}</strong> 条必需依赖</span>
          </div>
          <div class="dependency-item">
            <LockKeyhole :size="14" />
            <span><strong>{{ protectedCapabilityCount }}</strong> 个能力受依赖保护</span>
          </div>
          <div v-if="unresolvedReferenceCount > 0" class="dependency-item dependency-item-error">
            <CircleDot :size="14" />
            <span><strong>{{ unresolvedReferenceCount }}</strong> 个推荐引用不可用</span>
          </div>
          <div v-else class="dependency-item dependency-item-ok">
            <CircleCheck :size="14" />
            <span>推荐引用状态正常</span>
          </div>
        </div>
      </div>

    </div>

    <div class="security-footer">
      <ShieldCheck :size="14" />
      <span>所有能力执行均受权限控制与沙箱保护，操作可追溯</span>
      <i></i>
      <span>MicroMatrix Workbench</span>
      <i></i>
      <span>AI Capability Gateway</span>
    </div>
  </section>
</template>

<style scoped>
.gateway-panel {
  padding: 2px 0 4px;
}

.gateway-eyebrow-row {
  margin-bottom: 12px;
}

.gateway-eyebrow {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.16em;
  color: hsl(var(--muted-foreground));
}

.gateway-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: nowrap;
  gap: 14px;
}

.gateway-node {
  display: flex;
  width: 280px;
  min-width: 280px;
  max-width: 280px;
  align-items: center;
  gap: 12px;
  border: 1px solid;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 2%);
}

.gateway-node-ai {
  border-color: rgb(139 92 246 / 34%);
  background-color: rgb(139 92 246 / 8%);
  background-image: linear-gradient(145deg, rgb(139 92 246 / 15%), rgb(139 92 246 / 4%));
}

.gateway-node-catalog {
  border-color: rgb(59 130 246 / 34%);
  background-color: rgb(59 130 246 / 8%);
  background-image: linear-gradient(145deg, rgb(59 130 246 / 15%), rgb(59 130 246 / 4%));
}

.gateway-node-runtime {
  border-color: rgb(34 197 94 / 34%);
  background-color: rgb(34 197 94 / 8%);
  background-image: linear-gradient(145deg, rgb(34 197 94 / 15%), rgb(34 197 94 / 4%));
}

.gateway-node-icon {
  display: inline-flex;
  width: 42px;
  height: 42px;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 1px solid;
  border-radius: 50%;
}

.gateway-node-ai .gateway-node-icon {
  border-color: rgb(139 92 246 / 35%);
  background: rgb(139 92 246 / 12%);
  color: #8b5cf6;
}

.gateway-node-catalog .gateway-node-icon {
  border-color: rgb(59 130 246 / 35%);
  background: rgb(59 130 246 / 12%);
  color: #3b82f6;
}

.gateway-node-runtime .gateway-node-icon {
  border-color: rgb(34 197 94 / 35%);
  background: rgb(34 197 94 / 12%);
  color: #22c55e;
}

.gateway-node-copy {
  width: fit-content;
  min-width: 150px;
  text-align: center;
}

.gateway-node-copy strong,
.gateway-node-copy span {
  display: block;
}

.gateway-node-copy strong {
  font-size: 13px;
  font-weight: 600;
}

.gateway-node-copy span {
  margin-top: 2px;
  font-size: 10px;
  color: hsl(var(--foreground) / 0.72);
}

.gateway-node-copy p {
  margin: 8px auto 0;
  max-width: 210px;
  font-size: 10px;
  line-height: 16px;
  color: hsl(var(--muted-foreground));
}

.gateway-arrow {
  flex: none;
  color: hsl(var(--muted-foreground));
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.capability-card {
  min-height: 190px;
  border: 1px solid;
  border-radius: 10px;
  padding: 16px;
  text-align: left;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 2%);
  transition: transform 120ms ease, border-color 120ms ease, filter 120ms ease;
}

button.capability-card:hover {
  transform: translateY(-1px);
  filter: brightness(1.06);
}

.capability-card-static {
  cursor: default;
}

.capability-card-blue {
  border-color: rgb(59 130 246 / 32%);
  background-color: rgb(59 130 246 / 8%);
  background-image: linear-gradient(145deg, rgb(59 130 246 / 16%), rgb(59 130 246 / 5%));
}

.capability-card-violet {
  border-color: rgb(139 92 246 / 34%);
  background-color: rgb(139 92 246 / 8%);
  background-image: linear-gradient(145deg, rgb(139 92 246 / 17%), rgb(139 92 246 / 5%));
}

.capability-card-teal {
  border-color: rgb(20 184 166 / 34%);
  background-color: rgb(20 184 166 / 8%);
  background-image: linear-gradient(145deg, rgb(20 184 166 / 17%), rgb(20 184 166 / 5%));
}

.capability-card-amber {
  border-color: rgb(245 158 11 / 34%);
  background-color: rgb(245 158 11 / 9%);
  background-image: linear-gradient(145deg, rgb(245 158 11 / 17%), rgb(245 158 11 / 5%));
}

.capability-icon {
  display: inline-flex;
  height: 38px;
  width: 38px;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 1px solid;
  border-radius: 8px;
}

.capability-card-blue .capability-icon {
  border-color: rgb(59 130 246 / 30%);
  background: rgb(59 130 246 / 16%);
  color: #3b82f6;
}

.capability-card-violet .capability-icon {
  border-color: rgb(139 92 246 / 30%);
  background: rgb(139 92 246 / 16%);
  color: #8b5cf6;
}

.capability-card-teal .capability-icon {
  border-color: rgb(20 184 166 / 30%);
  background: rgb(20 184 166 / 16%);
  color: #14b8a6;
}

.capability-card-amber .capability-icon {
  border-color: rgb(245 158 11 / 30%);
  background: rgb(245 158 11 / 16%);
  color: #f59e0b;
}

.capability-body {
  display: flex;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  text-align: left;
}

.capability-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.capability-topline strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 24px;
  font-weight: 500;
}

.capability-title {
  margin-top: 14px;
  font-size: 14px;
  font-weight: 600;
}

.capability-body p {
  margin: 10px 0 0;
  font-size: 11px;
  line-height: 18px;
  color: hsl(var(--muted-foreground));
}

.capability-footer {
  margin-top: 22px;
  min-height: 38px;
  padding: 0 12px;
  font-size: 11px;
  border: 1px solid;
  border-radius: 7px;
}

.capability-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-weight: 500;
  transition: background-color 120ms ease, border-color 120ms ease, transform 120ms ease;
}

button.capability-card:hover .capability-link {
  transform: translateY(-1px);
}

.capability-card-violet .capability-link {
  color: #a78bfa;
  border-color: rgb(139 92 246 / 30%);
  background: rgb(139 92 246 / 6%);
}

.capability-card-teal .capability-link {
  color: #2dd4bf;
  border-color: rgb(20 184 166 / 30%);
  background: rgb(20 184 166 / 6%);
}

.capability-card-amber .capability-link {
  color: #fbbf24;
  border-color: rgb(245 158 11 / 30%);
  background: rgb(245 158 11 / 6%);
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.status-panel {
  min-height: 150px;
  border: 1px solid;
  border-radius: 10px;
  padding: 16px;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 2%);
}

.status-panel-green {
  border-color: rgb(34 197 94 / 28%);
  background-color: rgb(34 197 94 / 7%);
  background-image: linear-gradient(145deg, rgb(34 197 94 / 13%), rgb(34 197 94 / 3%));
}

.status-panel-sky {
  border-color: rgb(14 165 233 / 28%);
  background-color: rgb(14 165 233 / 7%);
  background-image: linear-gradient(145deg, rgb(14 165 233 / 13%), rgb(14 165 233 / 3%));
}

.status-panel-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  color: hsl(var(--foreground));
}

.status-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 16px;
}

.health-metric {
  display: flex;
  min-height: 72px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: 1px solid hsl(var(--border) / 0.55);
  border-radius: 7px;
  background: hsl(var(--background) / 0.35);
}

.status-metrics strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 22px;
  font-weight: 500;
}

.health-available {
  border-color: rgb(34 197 94 / 18%);
  background: rgb(34 197 94 / 6%);
}

.health-degraded {
  border-color: rgb(245 158 11 / 18%);
  background: rgb(245 158 11 / 6%);
}

.health-unavailable {
  border-color: rgb(239 68 68 / 18%);
  background: rgb(239 68 68 / 6%);
}

.health-available strong { color: #22c55e; }
.health-degraded strong { color: #f59e0b; }
.health-unavailable strong { color: #ef4444; }

.status-metrics span,
.health-metric small {
  font-size: 10px;
  color: hsl(var(--muted-foreground));
}

.health-metric small {
  font-size: 9px;
}

.dependency-list {
  display: grid;
  gap: 8px;
  margin-top: 16px;
}

.dependency-item {
  display: flex;
  min-height: 30px;
  align-items: center;
  gap: 8px;
  border-radius: 6px;
  padding: 0 8px;
  font-size: 10px;
  color: hsl(var(--muted-foreground));
  background: hsl(var(--background) / 0.28);
}

.dependency-item svg {
  flex: none;
  color: #38bdf8;
}

.dependency-item strong {
  color: hsl(var(--foreground));
  font-weight: 600;
}

.dependency-item-ok svg {
  color: #22c55e;
}

.dependency-item-error,
.dependency-item-error strong {
  color: hsl(var(--destructive));
}

.dependency-item-error svg {
  color: hsl(var(--destructive));
}

.security-footer {
  display: flex;
  min-height: 38px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-top: 1px solid hsl(var(--border));
  padding-top: 4px;
  font-size: 9px;
  color: hsl(var(--muted-foreground));
}

.security-footer svg {
  color: #64748b;
}

.security-footer i {
  width: 1px;
  height: 12px;
  background: hsl(var(--border));
}

@media (max-width: 1180px) {
  .capability-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .gateway-flow {
    flex-wrap: nowrap;
  }
}

@media (max-width: 980px) {
  .gateway-flow {
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .gateway-arrow {
    display: block;
    width: 16px;
    min-width: 16px;
    height: 16px;
    transform: rotate(90deg);
    flex-shrink: 0;
  }

  .gateway-node {
    width: min(100%, 420px);
    min-width: 0;
    max-width: 420px;
  }
}

@media (max-width: 820px) {
  .gateway-node {
    width: 100%;
    max-width: none;
  }

  .capability-grid,
  .status-grid {
    grid-template-columns: 1fr;
  }

  .security-footer {
    flex-wrap: wrap;
  }
}
</style>
