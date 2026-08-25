<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form'
import { Sheet } from '@/components/ui/sheet'
import type { WorkflowNodeKind } from '../../types'
import { useWorkflowEditorContext } from './workflowEditorContext'
import {
  nodeDefinitions,
  nodeGroups,
  nodeIcon,
  nodeRoleLabel,
  nodeRoles,
  type WorkflowNodeRole,
} from './workflowNodeModels'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; added: [nodeId: string] }>()
const editor = useWorkflowEditorContext()
const query = ref('')
const newNodeRole = ref<WorkflowNodeRole>('process')

const filteredNodeGroups = computed(() => {
  const value = query.value.trim().toLowerCase()
  if (!value) return nodeGroups
  return nodeGroups
    .map(group => ({
      ...group,
      kinds: group.kinds.filter(kind => [
        kind,
        nodeDefinitions[kind].label,
        nodeDefinitions[kind].description,
        group.label,
      ].some(text => text.toLowerCase().includes(value))),
    }))
    .filter(group => group.kinds.length > 0)
})

function defaultToolConfig(): Record<string, unknown> {
  const first = editor.catalog.value.effective_tools.find(item => item.provider === 'system')
    ?? editor.catalog.value.effective_tools[0]
  if (!first) return { provider: 'system', tool_name: '', arguments: {} }
  return {
    provider: first.provider,
    ...(first.provider === 'mcp' ? { connection_id: first.connection_id ?? '' } : {}),
    tool_name: first.tool_name,
    arguments: {},
  }
}

function defaultConfig(kind: WorkflowNodeKind): Record<string, unknown> {
  if (kind === 'skill') return { skill_id: editor.catalog.value.skills[0]?.id ?? '' }
  if (kind === 'tool') return defaultToolConfig()
  if (kind === 'approval') return { title: '确认后继续', description: '' }
  if (kind === 'condition') return { expression: 'true' }
  if (kind === 'artifact') return {
    artifact_id: `artifact-${Date.now().toString(36)}`,
    source_node_id: editor.nodes.value[0]?.id ?? '',
    format: 'json',
  }
  return {}
}

function addNode(kind: WorkflowNodeKind) {
  const index = editor.nodes.value.length
  const id = `${kind}-${Date.now().toString(36)}`
  const role: WorkflowNodeRole = index === 0 ? 'input' : newNodeRole.value
  const config = defaultConfig(kind)
  if (role === 'output') config.node_role = 'output'
  editor.nodes.value.push({
    id,
    type: 'workflow',
    position: { x: 80 + (index % 3) * 260, y: 100 + Math.floor(index / 3) * 160 },
    data: {
      label: nodeDefinitions[kind].label,
      kind,
      config,
      policy: { approval: kind === 'approval' ? 'required' : 'none', on_error: 'stop' },
      status: 'idle',
    },
  })
  if (role === 'input' || !editor.entryNodeId.value) editor.entryNodeId.value = id
  newNodeRole.value = 'process'
  emit('added', id)
}

watch(() => editor.nodes.value.length, length => {
  if (length === 0) newNodeRole.value = 'input'
}, { immediate: true })
</script>

<template>
  <Sheet :open="open" side="left" title="Node Library" width-class="w-[280px]" @close="emit('close')">
    <FormField label="搜索节点" class="mb-3">
      <div class="relative">
        <Search :size="13" class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <input v-model="query" class="pl-8" placeholder="Skill、Tool、Approval..." />
      </div>
    </FormField>

    <div class="mb-3">
      <div class="mb-2 text-[10px] font-medium text-muted-foreground">新增节点角色</div>
      <div class="grid grid-cols-3 gap-1.5">
        <Button
          v-for="role in nodeRoles"
          :key="role"
          :variant="newNodeRole === role ? 'secondary' : 'outline'"
          size="sm"
          class="h-7 px-2 text-[10px]"
          @click="newNodeRole = role"
        >{{ nodeRoleLabel(role) }}</Button>
      </div>
      <div class="mt-1.5 text-[9px] leading-4 text-muted-foreground">输入：仅输出；处理：输入 + 输出；输出：仅输入。</div>
    </div>

    <div class="grid gap-4">
      <div v-for="group in filteredNodeGroups" :key="group.label" class="grid gap-2">
        <div>
          <div class="text-[10px] font-medium">{{ group.label }}</div>
          <div class="mt-0.5 text-[9px] leading-4 text-muted-foreground">{{ group.description }}</div>
        </div>
        <button
          v-for="kind in group.kinds"
          :key="kind"
          type="button"
          class="flex w-full items-start justify-start gap-2 rounded-md border border-border bg-background px-2.5 py-2 text-left hover:bg-secondary"
          @click="addNode(kind)"
        >
          <component :is="nodeIcon(kind)" class="mt-0.5 flex-none text-muted-foreground" :size="14" />
          <span class="grid gap-0.5 text-left">
            <strong class="text-[11px] font-medium">{{ nodeDefinitions[kind].label }}</strong>
            <small class="text-[10px] leading-4 text-muted-foreground">{{ nodeDefinitions[kind].description }}</small>
          </span>
        </button>
      </div>
      <div v-if="!filteredNodeGroups.length" class="rounded-md border border-dashed border-border px-3 py-3 text-[10px] leading-4 text-muted-foreground">没有匹配的节点类型。</div>
    </div>

    <div class="mt-5 border-t border-border pt-3">
      <div class="mb-2 text-xs font-medium">Run</div>
      <select
        class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-[11px]"
        :value="editor.selectedRunId.value"
        @change="editor.selectedRunId.value = ($event.target as HTMLSelectElement).value; editor.refreshRuntimeState()"
      >
        <option value="">无运行记录</option>
        <option v-for="run in editor.runs.value.filter(item => item.workflow_id === editor.workflowId.value)" :key="run.run_id" :value="run.run_id">
          {{ run.status }} · {{ run.run_id.slice(0, 8) }}
        </option>
      </select>
      <div v-if="editor.selectedRun.value" class="mt-2 rounded-md border border-border bg-secondary/40 p-2 text-[10px] leading-4 text-muted-foreground">
        <div>状态：{{ editor.selectedRun.value.status }}</div>
        <div>Definition：v{{ editor.selectedRun.value.workflow_version }}</div>
        <div v-if="editor.selectedRun.value.error" class="mt-1 text-destructive">{{ editor.selectedRun.value.error }}</div>
      </div>
    </div>
  </Sheet>
</template>
