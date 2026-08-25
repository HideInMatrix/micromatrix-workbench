<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@lucide/vue'
import { FormField } from '@/components/ui/form'
import type { EffectiveToolDto } from '../../types'
import type { WorkflowCanvasNode } from '../../lib/workflowGraph'
import SchemaValueEditor from './SchemaValueEditor.vue'
import { useWorkflowEditorContext } from './workflowEditorContext'

const props = defineProps<{ node: WorkflowCanvasNode }>()
const editor = useWorkflowEditorContext()
const query = ref('')
const configError = ref('')

const selectedToolProvider = computed<'system' | 'mcp'>(() => (
  props.node.data.config.provider === 'mcp' ? 'mcp' : 'system'
))
const enabledMcpConnections = computed(() => editor.catalog.value.mcp_connections.filter(item => item.enabled))
const selectedTool = computed<EffectiveToolDto | null>(() => {
  const provider = selectedToolProvider.value
  const toolName = String(props.node.data.config.tool_name ?? '')
  const connectionId = String(props.node.data.config.connection_id ?? '')
  return editor.catalog.value.effective_tools.find(item => (
    item.provider === provider
    && item.tool_name === toolName
    && (provider === 'system' || item.connection_id === connectionId)
  )) ?? null
})
const selectedArgumentSchema = computed<Record<string, unknown>>(() => (
  selectedTool.value?.input_schema ?? { type: 'object', properties: {} }
))
const selectedArguments = computed<Record<string, unknown>>(() => {
  const value = props.node.data.config.arguments
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
})
const filteredSystemTools = computed(() => {
  const value = query.value.trim().toLowerCase()
  const selectedName = String(props.node.data.config.tool_name ?? '')
  return editor.catalog.value.effective_tools.filter(item => item.provider === 'system' && (
    item.tool_name === selectedName || !value
    || [item.tool_name, item.description, item.key].some(text => text.toLowerCase().includes(value))
  ))
})

function mcpTools(connectionId: string): EffectiveToolDto[] {
  return editor.catalog.value.effective_tools.filter(item => item.provider === 'mcp' && item.connection_id === connectionId)
}

function filteredMcpTools(connectionId: string): EffectiveToolDto[] {
  const value = query.value.trim().toLowerCase()
  const selectedName = String(props.node.data.config.tool_name ?? '')
  return mcpTools(connectionId).filter(item => (
    item.tool_name === selectedName || !value
    || [item.tool_name, item.description, item.key].some(text => text.toLowerCase().includes(value))
  ))
}

function setToolReference(provider: 'system' | 'mcp', connectionId: string | undefined, toolName: string) {
  const next: Record<string, unknown> = { ...props.node.data.config, provider, tool_name: toolName }
  if (provider === 'mcp') next.connection_id = connectionId ?? ''
  else delete next.connection_id
  props.node.data.config = next
}

function changeToolProvider(event: Event) {
  const provider = (event.target as HTMLSelectElement).value as 'system' | 'mcp'
  if (provider === 'system') {
    const first = editor.catalog.value.effective_tools.find(item => item.provider === 'system')
    setToolReference('system', undefined, first?.tool_name ?? '')
    return
  }
  const connection = enabledMcpConnections.value.find(item => mcpTools(item.id).length > 0) ?? enabledMcpConnections.value[0]
  setToolReference('mcp', connection?.id, connection ? mcpTools(connection.id)[0]?.tool_name ?? '' : '')
}

function changeMcpConnection(event: Event) {
  const connectionId = (event.target as HTMLSelectElement).value
  setToolReference('mcp', connectionId, mcpTools(connectionId)[0]?.tool_name ?? '')
}

function setVisualArguments(value: Record<string, unknown>) {
  props.node.data.config = { ...props.node.data.config, arguments: value }
  configError.value = ''
}

function setArguments(event: Event) {
  const raw = (event.target as HTMLTextAreaElement).value.trim()
  try {
    const parsed = raw ? JSON.parse(raw) : {}
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Arguments 必须是 JSON object')
    setVisualArguments(parsed as Record<string, unknown>)
  } catch (reason) {
    configError.value = reason instanceof Error ? reason.message : String(reason)
  }
}

function argumentsText(): string {
  return JSON.stringify(selectedArguments.value, null, 2)
}
</script>

<template>
  <div class="grid gap-3">
    <FormField label="搜索能力">
      <div class="relative">
        <Search :size="13" class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <input v-model="query" class="pl-8" placeholder="按名称、ID 或说明筛选" />
      </div>
    </FormField>
    <FormField label="Provider">
      <select :value="selectedToolProvider" @change="changeToolProvider"><option value="system">System</option><option value="mcp">MCP</option></select>
    </FormField>

    <FormField v-if="selectedToolProvider === 'system'" label="Tool">
      <select :value="node.data.config.tool_name" @change="setToolReference('system', undefined, ($event.target as HTMLSelectElement).value)">
        <option v-for="tool in filteredSystemTools" :key="tool.key" :value="tool.tool_name">{{ tool.tool_name }}</option>
      </select>
    </FormField>
    <template v-else>
      <FormField label="MCP Connection">
        <select :value="node.data.config.connection_id" @change="changeMcpConnection">
          <option v-for="connection in enabledMcpConnections" :key="connection.id" :value="connection.id">{{ connection.name }}</option>
        </select>
      </FormField>
      <FormField label="Tool">
        <select :value="node.data.config.tool_name" @change="setToolReference('mcp', String(node.data.config.connection_id ?? ''), ($event.target as HTMLSelectElement).value)">
          <option v-for="tool in filteredMcpTools(String(node.data.config.connection_id ?? ''))" :key="tool.key" :value="tool.tool_name">{{ tool.tool_name }}</option>
        </select>
      </FormField>
      <div v-if="!enabledMcpConnections.length" class="rounded-md border border-border bg-secondary/40 p-2 text-[10px] leading-4 text-muted-foreground">
        当前没有启用的 MCP Connection。请先在「MCP 服务」中添加并发现 Tools。
      </div>
    </template>

    <div v-if="selectedTool" class="rounded-md border border-border bg-secondary/40 p-2 text-[10px] leading-4 text-muted-foreground">
      <div>{{ selectedTool.description || 'No description' }}</div><div class="mt-1 font-mono">{{ selectedTool.key }}</div>
    </div>
    <div v-else-if="node.data.config.tool_name" class="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-[10px] leading-4 text-destructive">
      当前 Tool 引用不在 Effective Tool Catalog 中。MCP Connection 可能已禁用、删除或尚未完成 Tool Discovery。
    </div>

    <div class="grid gap-2">
      <div class="text-[10px] font-medium text-muted-foreground">Arguments</div>
      <SchemaValueEditor :schema="selectedArgumentSchema" :model-value="selectedArguments" @update:model-value="setVisualArguments" />
    </div>
    <details class="rounded-md border border-border bg-secondary/20 p-2">
      <summary class="cursor-pointer text-[10px] font-medium text-muted-foreground">Advanced JSON</summary>
      <textarea class="mt-2 min-h-28 w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-mono text-[10px] outline-none focus:ring-2 focus:ring-ring/30" :value="argumentsText()" spellcheck="false" @change="setArguments" />
    </details>
    <div v-if="configError" class="text-[10px] text-destructive">{{ configError }}</div>
  </div>
</template>
