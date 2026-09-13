<script setup lang="ts">
import { computed } from 'vue'
import { FormField } from '@/components/ui/form'
import type { ServerDraft } from '../../types'

const mode = defineModel<ServerDraft['permission_mode']>({ required: true })

defineProps<{
  disabled?: boolean
}>()

const options: Array<{
  value: ServerDraft['permission_mode']
  label: string
  description: string
}> = [
  {
    value: 'safe',
    label: '请求批准',
    description: '编辑外部文件和使用互联网时始终询问',
  },
  {
    value: 'trusted',
    label: '帮我批准',
    description: '仅对检测到的风险操作请求批准',
  },
  {
    value: 'dangerous',
    label: '完全访问权限',
    description: '可不受限制地访问互联网和你电脑上的任何文件',
  },
]

const selected = computed(() => (
  options.find(item => item.value === mode.value) ?? options[0]
))
</script>

<template>
  <FormField label="权限模式">
    <select v-model="mode" :disabled="disabled">
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
    <small
      :class="[
        'text-[10px] leading-4 font-normal',
        selected.value === 'dangerous' ? 'text-destructive' : 'text-muted-foreground',
      ]"
    >
      {{ selected.description }}
    </small>
  </FormField>
</template>
