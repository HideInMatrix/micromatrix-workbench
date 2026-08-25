<script setup lang="ts">
import { ref } from 'vue'
import { FormField } from '@/components/ui/form'
import ObjectSchemaBuilder from './ObjectSchemaBuilder.vue'
import { useWorkflowEditorContext } from './workflowEditorContext'

const editor = useWorkflowEditorContext()
const schemaError = ref('')

function schemaText(): string {
  return JSON.stringify(editor.workflowInputsSchema.value, null, 2)
}

function setInputsSchema(event: Event) {
  const raw = (event.target as HTMLTextAreaElement).value.trim()
  try {
    const parsed = raw ? JSON.parse(raw) : { type: 'object', additionalProperties: true }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Inputs Schema 必须是 JSON object')
    editor.workflowInputsSchema.value = parsed as Record<string, unknown>
    schemaError.value = ''
  } catch (reason) {
    schemaError.value = reason instanceof Error ? reason.message : String(reason)
  }
}

function setTags(event: Event) {
  editor.workflowTags.value = (event.target as HTMLInputElement).value
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
}
</script>

<template>
  <div class="grid gap-3">
    <FormField label="Workflow ID"><input v-model="editor.workflowId.value" /></FormField>
    <FormField label="Tags（逗号分隔）">
      <input :value="editor.workflowTags.value.join(', ')" placeholder="frontend, review" @change="setTags" />
    </FormField>
    <div class="grid gap-2">
      <div class="text-[10px] font-medium text-muted-foreground">Inputs Schema</div>
      <ObjectSchemaBuilder v-model="editor.workflowInputsSchema.value" />
    </div>
    <details class="rounded-md border border-border bg-secondary/20 p-2">
      <summary class="cursor-pointer text-[10px] font-medium text-muted-foreground">Advanced JSON Schema</summary>
      <textarea
        class="mt-2 min-h-40 w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-mono text-[10px] outline-none focus:ring-2 focus:ring-ring/30"
        :value="schemaText()"
        spellcheck="false"
        @change="setInputsSchema"
      />
    </details>
    <div v-if="schemaError" class="text-[10px] leading-4 text-destructive">{{ schemaError }}</div>
    <div class="rounded-md border border-border bg-secondary/40 p-2 text-[10px] leading-4 text-muted-foreground">
      Description、Tags 与 Inputs Schema 会进入 workflow_list，供 AI 判断 Workflow 用途与调用参数。坐标只决定 Vue Flow 布局；Runtime 执行顺序只由 Entry Node、Edge 和 Edge Condition 决定。
    </div>
  </div>
</template>
