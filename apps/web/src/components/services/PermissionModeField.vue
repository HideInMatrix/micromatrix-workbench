<script setup lang="ts">
import { FormField } from '@/components/ui/form'
import type { RuntimeDraft } from '../../types'

const mode = defineModel<RuntimeDraft['permission_mode']>({ required: true })

defineProps<{
  disabled?: boolean
}>()

const options: Array<{
  value: RuntimeDraft['permission_mode']
  label: string
}> = [
  {
    value: 'safe',
    label: '请求批准',
  },
  {
    value: 'trusted',
    label: '帮我批准',
  },
  {
    value: 'dangerous',
    label: '完全访问权限',
  },
]
</script>

<template>
  <FormField label="权限模式">
    <select v-model="mode" :disabled="disabled">
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
  </FormField>
</template>
