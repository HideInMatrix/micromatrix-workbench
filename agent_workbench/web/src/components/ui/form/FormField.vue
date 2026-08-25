<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  label?: string
  span?: '1' | '2'
}>()
</script>

<template>
  <label
    :class="cn(
      'grid gap-1.5 text-[11px] font-medium leading-4 text-foreground',
      '[&>input]:h-8 [&>input]:w-full [&>input]:rounded-md [&>input]:border [&>input]:border-input [&>input]:bg-background [&>input]:px-2.5 [&>input]:text-xs [&>input]:font-normal [&>input]:text-foreground [&>input]:outline-none [&>input]:transition-[border-color,box-shadow]',
      '[&>select]:h-8 [&>select]:w-full [&>select]:rounded-md [&>select]:border [&>select]:border-input [&>select]:bg-background [&>select]:px-2.5 [&>select]:text-xs [&>select]:font-normal [&>select]:text-foreground [&>select]:outline-none [&>select]:transition-[border-color,box-shadow]',
      '[&>textarea]:w-full [&>textarea]:rounded-md [&>textarea]:border [&>textarea]:border-input [&>textarea]:bg-background [&>textarea]:px-2.5 [&>textarea]:py-2 [&>textarea]:font-mono [&>textarea]:text-xs [&>textarea]:font-normal [&>textarea]:leading-[18px] [&>textarea]:text-foreground [&>textarea]:outline-none [&>textarea]:transition-[border-color,box-shadow]',
      '[&>input:focus]:border-ring [&>input:focus]:ring-2 [&>input:focus]:ring-ring/15',
      '[&>select:focus]:border-ring [&>select:focus]:ring-2 [&>select:focus]:ring-ring/15',
      '[&>textarea:focus]:border-ring [&>textarea:focus]:ring-2 [&>textarea:focus]:ring-ring/15',
      '[&>input:disabled]:bg-muted [&>input:disabled]:text-muted-foreground',
      '[&>select:disabled]:bg-muted [&>select:disabled]:text-muted-foreground',
      '[&>textarea:disabled]:bg-muted [&>textarea:disabled]:text-muted-foreground',
      props.span === '2' && 'col-span-2',
      props.class,
    )"
  >
    <span v-if="props.label">{{ props.label }}</span>
    <slot />
  </label>
</template>
