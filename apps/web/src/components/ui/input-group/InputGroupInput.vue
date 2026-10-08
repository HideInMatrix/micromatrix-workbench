<script setup lang="ts">
import type { HTMLAttributes, InputHTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })

interface Props extends /* @vue-ignore */ InputHTMLAttributes {
  modelValue?: string | number | undefined
  class?: HTMLAttributes['class']
}
const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function handleInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}
</script>

<template>
  <input
    v-bind="$attrs"
    data-slot="input-group-control"
    :value="props.modelValue"
    :class="cn(
      'h-full min-w-0 flex-1 border-0 bg-transparent px-3 text-xs text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:bg-transparent disabled:text-muted-foreground',
      props.class,
    )"
    @input="handleInput"
  />
</template>
