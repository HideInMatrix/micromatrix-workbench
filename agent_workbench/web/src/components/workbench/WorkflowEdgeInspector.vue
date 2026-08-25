<script setup lang="ts">
import { computed } from 'vue'
import { FormField } from '@/components/ui/form'
import type { WorkflowCanvasEdge } from '../../lib/workflowGraph'
import type { WorkflowEdgeDto } from '../../types'
import { useWorkflowEditorContext } from './workflowEditorContext'

const props = defineProps<{ edge: WorkflowCanvasEdge }>()
const editor = useWorkflowEditorContext()
const conditions: WorkflowEdgeDto['condition'][] = ['success', 'failure', 'approved', 'rejected', 'true', 'false']
const issues = computed(() => [
  ...(editor.validation.value?.errors ?? []),
  ...(editor.validation.value?.warnings ?? []),
].filter(item => item.subject === props.edge.id))

function setCondition(value: WorkflowEdgeDto['condition']) {
  props.edge.data = { condition: value }
  props.edge.label = value
}
</script>

<template>
  <div class="grid gap-3">
    <div v-if="issues.length" class="grid gap-1 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-[10px] leading-4 text-destructive">
      <div v-for="issue in issues" :key="`${issue.code}-${issue.message}`">{{ issue.message }}</div>
    </div>
    <FormField label="Edge"><input :value="edge.id" disabled /></FormField>
    <FormField label="Condition">
      <select :value="edge.data?.condition" @change="setCondition(($event.target as HTMLSelectElement).value as WorkflowEdgeDto['condition'])">
        <option v-for="condition in conditions" :key="condition" :value="condition">{{ condition }}</option>
      </select>
    </FormField>
  </div>
</template>
