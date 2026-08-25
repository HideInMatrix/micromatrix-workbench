<script setup lang="ts">
import { computed } from 'vue'
import { Braces, Check, Copy, ShieldCheck, Trash2, X } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/sheet'
import WorkflowEdgeInspector from './WorkflowEdgeInspector.vue'
import WorkflowMetadataInspector from './WorkflowMetadataInspector.vue'
import WorkflowNodeInspector from './WorkflowNodeInspector.vue'
import { useWorkflowEditorContext } from './workflowEditorContext'
import { withoutNodeRole } from './workflowNodeModels'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const selectedNodeId = defineModel<string>('selectedNodeId', { required: true })
const selectedEdgeId = defineModel<string>('selectedEdgeId', { required: true })
const editor = useWorkflowEditorContext()

const selectedNode = computed(() => editor.nodes.value.find(node => node.id === selectedNodeId.value) ?? null)
const selectedEdge = computed(() => editor.edges.value.find(edge => edge.id === selectedEdgeId.value) ?? null)

function duplicateSelectedNode() {
  if (!selectedNode.value) return
  const original = selectedNode.value
  const id = `${original.data.kind}-${Date.now().toString(36)}`
  const config = withoutNodeRole(JSON.parse(JSON.stringify(original.data.config)) as Record<string, unknown>)
  editor.nodes.value.push({
    id,
    type: 'workflow',
    position: { x: original.position.x + 36, y: original.position.y + 36 },
    data: {
      label: `${original.data.label} Copy`,
      kind: original.data.kind,
      config,
      policy: { ...original.data.policy },
      status: 'idle',
    },
  })
  selectedNodeId.value = id
  selectedEdgeId.value = ''
}

function nextEntryNodeId(removedNodeId: string): string {
  const nodes = editor.nodes.value.filter(node => node.id !== removedNodeId)
  const edges = editor.edges.value.filter(edge => edge.source !== removedNodeId && edge.target !== removedNodeId)
  return (nodes.find(node => !edges.some(edge => edge.target === node.id)) ?? nodes[0])?.id ?? ''
}

function removeSelected() {
  const label = selectedNode.value?.data.label ?? selectedEdge.value?.id ?? '当前选择'
  if (!window.confirm(`确认删除「${label}」？`)) return
  if (selectedNode.value) {
    const id = selectedNode.value.id
    const nextEntry = editor.entryNodeId.value === id ? nextEntryNodeId(id) : editor.entryNodeId.value
    editor.nodes.value = editor.nodes.value.filter(node => node.id !== id)
    editor.edges.value = editor.edges.value.filter(edge => edge.source !== id && edge.target !== id)
    editor.entryNodeId.value = nextEntry
    selectedNodeId.value = ''
    return
  }
  if (!selectedEdge.value) return
  editor.edges.value = editor.edges.value.filter(edge => edge.id !== selectedEdge.value?.id)
  selectedEdgeId.value = ''
}
</script>

<template>
  <Sheet :open="open" side="right" title="Inspector" width-class="w-[340px]" @close="emit('close')">
    <div class="mb-3 flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 text-xs font-medium"><Braces :size="14" />当前选择</div>
      <div class="flex items-center gap-1">
        <Button v-if="selectedNode" variant="ghost" size="icon" class="h-7 w-7" title="复制节点" @click="duplicateSelectedNode"><Copy :size="13" /></Button>
        <Button v-if="selectedNode || selectedEdge" variant="ghost" size="icon" class="h-7 w-7 text-destructive" title="删除" @click="removeSelected"><Trash2 :size="13" /></Button>
      </div>
    </div>

    <WorkflowNodeInspector v-if="selectedNode" :node="selectedNode" />
    <WorkflowEdgeInspector v-else-if="selectedEdge" :edge="selectedEdge" />
    <WorkflowMetadataInspector v-else />

    <div v-if="editor.workflowApprovals.value.length" class="mt-5 border-t border-border pt-3">
      <div class="mb-2 flex items-center gap-2 text-xs font-medium"><ShieldCheck :size="14" />待人工审批</div>
      <div v-for="approval in editor.workflowApprovals.value" :key="approval.request_id" class="mb-2 rounded-md border border-yellow-400/60 bg-yellow-400/10 p-2">
        <div class="text-[11px] font-medium">{{ approval.title }}</div>
        <div class="mt-1 text-[10px] leading-4 text-muted-foreground">{{ approval.description || approval.node_id }}</div>
        <div class="mt-2 flex gap-1.5">
          <Button size="sm" class="h-7 bg-yellow-400 px-2 text-[10px] !text-black hover:bg-yellow-300" @click="editor.respondApproval(approval.request_id, true)"><Check :size="12" />批准</Button>
          <Button variant="outline" size="sm" class="h-7 px-2 text-[10px]" @click="editor.respondApproval(approval.request_id, false)"><X :size="12" />拒绝</Button>
        </div>
      </div>
    </div>
  </Sheet>
</template>
