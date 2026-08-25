<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@lucide/vue'
import { FormField } from '@/components/ui/form'
import type { WorkflowCanvasNode } from '../../lib/workflowGraph'
import { useWorkflowEditorContext } from './workflowEditorContext'
import { nodeRole, withoutNodeRole, type WorkflowNodeRole } from './workflowNodeModels'
import WorkflowToolInspector from './WorkflowToolInspector.vue'

const props = defineProps<{ node: WorkflowCanvasNode }>()
const editor = useWorkflowEditorContext()
const roleError = ref('')
const capabilityQuery = ref('')

const issues = computed(() => [
  ...(editor.validation.value?.errors ?? []),
  ...(editor.validation.value?.warnings ?? []),
].filter(item => item.subject === props.node.id))

const selectedNodeRole = computed<WorkflowNodeRole>(() => (
  nodeRole(props.node.id, editor.entryNodeId.value, props.node.data.config)
))
const selectedSkill = computed(() => {
  if (props.node.data.kind !== 'skill') return null
  const id = String(props.node.data.config.skill_id ?? '')
  return editor.catalog.value.skills.find(item => item.id === id) ?? null
})
const filteredSkills = computed(() => {
  const query = capabilityQuery.value.trim().toLowerCase()
  const selectedId = String(props.node.data.config.skill_id ?? '')
  if (!query) return editor.catalog.value.skills
  return editor.catalog.value.skills.filter(item => (
    item.id === selectedId
    || [item.id, item.name, item.description].some(value => value.toLowerCase().includes(query))
  ))
})

function setNodeConfig(key: string, value: unknown) {
  props.node.data.config = { ...props.node.data.config, [key]: value }
}

function setEntryNode() {
  if (editor.edges.value.some(edge => edge.target === props.node.id)) {
    roleError.value = '输入节点不能存在入边。请先删除指向该节点的连线。'
    return false
  }
  editor.entryNodeId.value = props.node.id
  if (props.node.data.config.node_role === 'output') {
    props.node.data.config = withoutNodeRole(props.node.data.config)
  }
  roleError.value = ''
  return true
}

function setNodeRole(role: WorkflowNodeRole) {
  if (role === 'input') {
    setEntryNode()
    return
  }
  if (props.node.id === editor.entryNodeId.value) {
    roleError.value = '当前节点是 Workflow 入口。请先将其他节点设为输入节点，再修改它的角色。'
    return
  }
  if (role === 'output' && editor.edges.value.some(edge => edge.source === props.node.id)) {
    roleError.value = '输出节点不能存在出边。请先删除从该节点出发的连线。'
    return
  }
  props.node.data.config = role === 'output'
    ? { ...props.node.data.config, node_role: 'output' }
    : withoutNodeRole(props.node.data.config)
  roleError.value = ''
}

function changeNodeRole(event: Event) {
  setNodeRole((event.target as HTMLSelectElement).value as WorkflowNodeRole)
}
</script>

<template>
  <div class="grid gap-3">
    <div v-if="issues.length" class="grid gap-1 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-[10px] leading-4 text-destructive">
      <div v-for="issue in issues" :key="`${issue.code}-${issue.message}`">{{ issue.message }}</div>
    </div>

    <FormField label="名称"><input v-model="node.data.label" /></FormField>
    <FormField label="Node ID"><input :value="node.id" disabled /></FormField>
    <FormField label="节点角色">
      <select :value="selectedNodeRole" @change="changeNodeRole">
        <option value="input">输入节点</option><option value="process">处理节点</option><option value="output">输出节点</option>
      </select>
    </FormField>
    <div v-if="roleError" class="text-[10px] leading-4 text-destructive">{{ roleError }}</div>

    <FormField v-if="node.data.kind === 'skill'" label="搜索能力">
      <div class="relative">
        <Search :size="13" class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <input v-model="capabilityQuery" class="pl-8" placeholder="按名称、ID 或说明筛选" />
      </div>
    </FormField>

    <template v-if="node.data.kind === 'skill'">
      <FormField label="Skill">
        <select :value="node.data.config.skill_id" @change="setNodeConfig('skill_id', ($event.target as HTMLSelectElement).value)">
          <option v-for="skill in filteredSkills" :key="skill.id" :value="skill.id">{{ skill.name }}</option>
        </select>
      </FormField>
      <div v-if="selectedSkill" class="rounded-md border border-border bg-secondary/40 p-2 text-[10px] leading-4 text-muted-foreground">{{ selectedSkill.description }}</div>
      <div v-else-if="node.data.config.skill_id" class="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-[10px] leading-4 text-destructive">当前 Skill 引用已失效。请重新选择 Skill。</div>
    </template>

    <WorkflowToolInspector v-if="node.data.kind === 'tool'" :node="node" />

    <template v-if="node.data.kind === 'approval'">
      <FormField label="标题"><input :value="node.data.config.title" @input="setNodeConfig('title', ($event.target as HTMLInputElement).value)" /></FormField>
      <FormField label="说明"><input :value="node.data.config.description" @input="setNodeConfig('description', ($event.target as HTMLInputElement).value)" /></FormField>
    </template>

    <FormField v-if="node.data.kind === 'condition'" label="受限表达式">
      <input :value="node.data.config.expression" @input="setNodeConfig('expression', ($event.target as HTMLInputElement).value)" />
    </FormField>

    <template v-if="node.data.kind === 'artifact'">
      <FormField label="Artifact ID"><input :value="node.data.config.artifact_id" @input="setNodeConfig('artifact_id', ($event.target as HTMLInputElement).value)" /></FormField>
      <FormField label="Source Node">
        <select :value="node.data.config.source_node_id" @change="setNodeConfig('source_node_id', ($event.target as HTMLSelectElement).value)">
          <option v-for="item in editor.nodes.value.filter(candidate => candidate.id !== node.id)" :key="item.id" :value="item.id">{{ item.data.label }}</option>
        </select>
      </FormField>
      <FormField label="Format">
        <select :value="node.data.config.format" @change="setNodeConfig('format', ($event.target as HTMLSelectElement).value)">
          <option value="json">json</option><option value="text">text</option>
        </select>
      </FormField>
    </template>

    <FormField label="on_error">
      <select v-model="node.data.policy.on_error"><option value="stop">stop</option><option value="continue">continue</option></select>
    </FormField>
  </div>
</template>
