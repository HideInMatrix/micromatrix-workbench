<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CheckCircle2,
  CircleStop,
  PanelLeftOpen,
  PanelRightOpen,
  Plus,
  Redo2,
  Save,
  Scan,
  Trash2,
  Undo2,
} from '@lucide/vue'
import { Handle, Position, VueFlow, useVueFlow, type Connection } from '@vue-flow/core'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form'
import { useWorkflowEditor } from '../composables/useWorkflowEditor'
import type { WorkflowCanvasEdge, WorkflowCanvasNode } from '../lib/workflowGraph'
import WorkflowInspector from './workbench/WorkflowInspector.vue'
import WorkflowNodeLibrary from './workbench/WorkflowNodeLibrary.vue'
import { provideWorkflowEditor } from './workbench/workflowEditorContext'
import {
  defaultEdgeCondition,
  nodeIcon,
  nodeKindBorderClass,
  nodeRole,
  nodeStateClass,
} from './workbench/workflowNodeModels'

const editor = useWorkflowEditor()
provideWorkflowEditor(editor)
const selectedNodeId = ref('')
const selectedEdgeId = ref('')
const nodeLibraryOpen = ref(false)
const inspectorOpen = ref(false)
const canvasHost = ref<HTMLElement | null>(null)
const { fitView, onPaneReady, setViewport } = useVueFlow()
let paneReady = false
let resizeObserver: ResizeObserver | null = null
let fitTimer = 0
let fitRaf = 0
let fitRafAfterLayout = 0
let lastCanvasWidth = 0
let lastCanvasHeight = 0

const canDeleteWorkflow = computed(() => (
  editor.workflowScope.value === 'workspace'
  && editor.catalog.value.workflows.some(item => item.id === editor.workflowId.value && item.scope === 'workspace')
))

function cancelScheduledFit() {
  window.clearTimeout(fitTimer)
  window.cancelAnimationFrame(fitRaf)
  window.cancelAnimationFrame(fitRafAfterLayout)
  fitTimer = 0
  fitRaf = 0
  fitRafAfterLayout = 0
}

function scheduleFitView(duration = 0, delay = 60) {
  if (!paneReady || !editor.nodes.value.length) return
  cancelScheduledFit()
  fitTimer = window.setTimeout(async () => {
    await nextTick()
    fitRaf = window.requestAnimationFrame(() => {
      fitRafAfterLayout = window.requestAnimationFrame(() => void fitView({ padding: 0.18, duration }))
    })
  }, delay)
}

function fitCanvas() {
  if (!editor.nodes.value.length) {
    void setViewport({ x: 0, y: 0, zoom: 1 })
    return
  }
  scheduleFitView(180, 0)
}

async function changeTarget(event: Event) {
  await editor.loadTarget((event.target as HTMLSelectElement).value)
  scheduleFitView(0, 80)
}

async function changeWorkflow(event: Event) {
  await editor.loadWorkflow((event.target as HTMLSelectElement).value)
  scheduleFitView(0, 80)
}

function validationIssues(subject: string) {
  return [
    ...(editor.validation.value?.errors ?? []),
    ...(editor.validation.value?.warnings ?? []),
  ].filter(item => item.subject === subject)
}

function nodeValidationClass(nodeId: string): string {
  return editor.validation.value?.errors.some(item => item.subject === nodeId)
    ? 'ring-2 ring-destructive/60 ring-offset-1 ring-offset-background'
    : ''
}

function onConnect(connection: Connection) {
  if (!connection.source || !connection.target || connection.source === connection.target) return
  const source = editor.nodes.value.find(node => node.id === connection.source)
  const target = editor.nodes.value.find(node => node.id === connection.target)
  if (!source || !target) return
  if (nodeRole(source.id, editor.entryNodeId.value, source.data.config) === 'output') return
  if (nodeRole(target.id, editor.entryNodeId.value, target.data.config) === 'input') return
  if (editor.edges.value.some(edge => edge.source === connection.source && edge.target === connection.target)) return
  const condition = defaultEdgeCondition(source.data.kind)
  const id = `${connection.source}-${connection.target}-${Date.now().toString(36)}`
  editor.edges.value.push({ id, source: connection.source, target: connection.target, label: condition, data: { condition } })
  selectedEdgeId.value = id
  selectedNodeId.value = ''
  inspectorOpen.value = true
}

function selectNode(node: WorkflowCanvasNode) {
  selectedNodeId.value = node.id
  selectedEdgeId.value = ''
  inspectorOpen.value = true
}

function selectEdge(edge: WorkflowCanvasEdge) {
  selectedEdgeId.value = edge.id
  selectedNodeId.value = ''
  inspectorOpen.value = true
}

function clearSelection() {
  selectedNodeId.value = ''
  selectedEdgeId.value = ''
}

function handleNodeAdded(nodeId: string) {
  selectedNodeId.value = nodeId
  selectedEdgeId.value = ''
  nodeLibraryOpen.value = false
  inspectorOpen.value = true
  scheduleFitView(160, 80)
}

async function removeWorkflow() {
  if (!canDeleteWorkflow.value) return
  if (!window.confirm(`确认删除 Workflow「${editor.workflowName.value}」？`)) return
  await editor.remove()
}

function handleResize(entries: ResizeObserverEntry[]) {
  const entry = entries[0]
  if (!entry) return
  const { width, height } = entry.contentRect
  if (width <= 0 || height <= 0) return
  if (Math.abs(width - lastCanvasWidth) < 1 && Math.abs(height - lastCanvasHeight) < 1) return
  lastCanvasWidth = width
  lastCanvasHeight = height
  scheduleFitView(120, 120)
}

onPaneReady(() => {
  paneReady = true
  scheduleFitView(0, 0)
})

watch(() => editor.workflowId.value, () => {
  selectedNodeId.value = editor.nodes.value[0]?.id ?? ''
  selectedEdgeId.value = ''
  scheduleFitView(0, 80)
}, { flush: 'post' })

onMounted(async () => {
  await editor.refreshTargets()
  editor.startPolling()
  await nextTick()
  const host = canvasHost.value
  if (host && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(host)
  }
  scheduleFitView(0, 0)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  cancelScheduledFit()
})
</script>

<template>
  <section class="flex min-h-0 w-full flex-1 flex-col gap-3">
    <header class="flex min-h-10 items-start justify-between gap-4">
      <div>
        <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">Workflow Editor</h1>
        <p class="mt-1 mb-0 text-xs leading-[18px] text-muted-foreground">
          Workflow 是可被 AI 选择的 Capability。Vue Flow 只编辑 Definition，Runtime 只执行 Graph，不负责理解用户意图或自动路由任务。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="!editor.canUndo.value" title="撤销" @click="editor.undo()"><Undo2 :size="14" />撤销</Button>
        <Button variant="outline" size="sm" :disabled="!editor.canRedo.value" title="重做" @click="editor.redo()"><Redo2 :size="14" />重做</Button>
        <Button variant="outline" size="sm" :disabled="editor.busy.value" @click="editor.validate()"><CheckCircle2 :size="14" />验证</Button>
        <Button size="sm" :disabled="editor.busy.value || !editor.targetId.value" @click="editor.save()"><Save :size="14" />保存</Button>
      </div>
    </header>

    <div v-if="editor.error.value" class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{{ editor.error.value }}</div>

    <div class="grid grid-cols-[minmax(220px,0.8fr)_minmax(240px,1fr)_auto] items-end gap-3 rounded-lg border border-border bg-card p-3">
      <FormField label="Workspace Target">
        <select :value="editor.targetId.value" @change="changeTarget">
          <option v-for="target in editor.targets.value" :key="target.target_id" :value="target.target_id">{{ target.service_name }} / {{ target.profile_name }}</option>
        </select>
      </FormField>
      <FormField label="Workflow">
        <select :value="editor.workflowId.value" @change="changeWorkflow">
          <option v-for="workflow in editor.catalog.value.workflows" :key="workflow.id" :value="workflow.id">{{ workflow.name }} · v{{ workflow.version }} · {{ workflow.scope }}</option>
        </select>
      </FormField>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="editor.newWorkflow()"><Plus :size="14" />新建</Button>
        <Button variant="outline" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" :disabled="editor.busy.value || !canDeleteWorkflow" :title="canDeleteWorkflow ? '删除当前 Workspace Workflow' : '内置 Workflow 或未保存 Workflow 不可删除'" @click="removeWorkflow"><Trash2 :size="14" />删除</Button>
      </div>
    </div>

    <div class="grid grid-cols-[minmax(220px,0.7fr)_minmax(320px,1.3fr)] gap-3 rounded-lg border border-border bg-card p-3">
      <FormField label="名称"><input v-model="editor.workflowName.value" placeholder="Workflow 名称" /></FormField>
      <FormField label="Workflow 描述（AI Discovery 必填）"><input v-model="editor.workflowDescription.value" placeholder="说明这个 Workflow 解决什么问题、何时应该使用" /></FormField>
    </div>

    <div ref="canvasHost" class="relative min-h-[560px] flex-1 overflow-hidden rounded-lg border border-border bg-background">
      <div class="absolute top-3 left-3 z-20 flex items-center gap-2">
        <Button variant="outline" size="sm" class="bg-background/95 shadow-sm" @click="nodeLibraryOpen = true"><PanelLeftOpen :size="14" />节点库</Button>
        <Button variant="outline" size="sm" class="bg-background/95 shadow-sm" title="适配全部节点" @click="fitCanvas"><Scan :size="14" />适配视图</Button>
      </div>
      <div class="absolute top-3 right-3 z-20">
        <Button variant="outline" size="sm" class="bg-background/95 shadow-sm" @click="inspectorOpen = true"><PanelRightOpen :size="14" />Inspector</Button>
      </div>

      <VueFlow
        v-model:nodes="editor.nodes.value"
        v-model:edges="editor.edges.value"
        :min-zoom="0.3"
        :max-zoom="1.8"
        class="absolute inset-0 h-full w-full"
        @connect="onConnect"
        @node-click="({ node }) => selectNode(node as WorkflowCanvasNode)"
        @edge-click="({ edge }) => selectEdge(edge as WorkflowCanvasEdge)"
        @pane-click="clearSelection"
      >
        <template #node-workflow="{ id, data, selected }">
          <div :class="['relative min-w-[170px] rounded-lg border px-3 py-2 shadow-sm transition-colors', nodeKindBorderClass(data.kind), nodeStateClass(data.status, selected), nodeValidationClass(id)]">
            <Handle v-if="nodeRole(id, editor.entryNodeId.value, data.config) !== 'input'" class="workflow-handle workflow-handle-target" type="target" :position="Position.Left" />
            <div class="flex items-center gap-2"><component :is="nodeIcon(data.kind)" :size="14" class="text-muted-foreground" /><strong class="text-[11px] font-medium">{{ data.label }}</strong></div>
            <div class="mt-1 font-mono text-[9px] uppercase tracking-wide text-muted-foreground">{{ nodeRole(id, editor.entryNodeId.value, data.config) }} · {{ data.kind }}<span v-if="data.status !== 'idle'"> · {{ data.status }}</span></div>
            <span v-if="validationIssues(id).length" class="absolute -top-2 -right-2 flex h-5 min-w-5 items-center justify-center rounded-full border border-background bg-destructive px-1 text-[9px] font-medium text-destructive-foreground" :title="validationIssues(id).map(item => item.message).join('\n')">{{ validationIssues(id).length }}</span>
            <Handle v-if="nodeRole(id, editor.entryNodeId.value, data.config) !== 'output'" class="workflow-handle workflow-handle-source" type="source" :position="Position.Right" />
          </div>
        </template>
      </VueFlow>

      <button v-if="!editor.nodes.value.length" type="button" class="absolute top-1/2 left-1/2 z-10 grid -translate-x-1/2 -translate-y-1/2 gap-1 rounded-lg border border-dashed border-border bg-background/95 px-6 py-5 text-center hover:bg-secondary" @click="nodeLibraryOpen = true">
        <strong class="text-xs font-medium">从节点库开始编排</strong><span class="text-[10px] leading-4 text-muted-foreground">添加 Skill、Tool 或 Flow Control 节点</span>
      </button>
      <div class="pointer-events-none absolute right-3 bottom-3 z-20 rounded-md border border-border bg-background/90 px-2 py-1 font-mono text-[10px] text-muted-foreground shadow-sm">{{ editor.nodes.value.length }} Nodes · {{ editor.edges.value.length }} Edges</div>

      <WorkflowNodeLibrary :open="nodeLibraryOpen" @close="nodeLibraryOpen = false" @added="handleNodeAdded" />
      <WorkflowInspector v-model:selected-node-id="selectedNodeId" v-model:selected-edge-id="selectedEdgeId" :open="inspectorOpen" @close="inspectorOpen = false" />
    </div>

    <div class="flex min-h-9 items-center justify-between gap-3 rounded-md border border-border bg-secondary/40 px-3 py-2 text-[11px]">
      <span class="min-w-0 text-muted-foreground">{{ editor.notice.value || '保存前始终使用 Python Workflow Validator 验证。' }}</span>
      <div class="flex flex-none items-center gap-2 font-mono text-[10px] text-muted-foreground">
        <span>{{ editor.workflowScope.value }}</span><span>v{{ editor.workflowVersion.value }}</span>
        <span v-if="editor.selectedTarget.value?.running" class="text-green-500">Runtime Running</span>
        <span v-else class="flex items-center gap-1"><CircleStop :size="10" />Runtime Stopped</span>
      </div>
    </div>
  </section>
</template>
