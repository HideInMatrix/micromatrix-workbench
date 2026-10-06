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

const descriptions: Record<RuntimeDraft['permission_mode'], string> = {
  safe: '文件修改与 Shell 命令都需要弹窗确认；只读工具直接执行。',
  trusted: '自动批准文件修改；Shell 命令仍需要弹窗确认。',
  dangerous: '不再弹窗审批。工具具有当前服务账户的权限，不是沙箱。',
}
</script>

<template>
  <FormField label="权限模式">
    <select v-model="mode" :disabled="disabled">
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
    <p class="mt-1.5 mb-0 text-xs leading-5 text-muted-foreground">{{ descriptions[mode] }}</p>
  </FormField>
</template>
