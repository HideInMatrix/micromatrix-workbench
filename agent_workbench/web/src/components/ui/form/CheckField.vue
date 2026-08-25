<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <label
    :class="cn(
      'flex items-start gap-2 text-[11px] leading-[17px] text-muted-foreground [&>input]:mt-0.5',
      props.class,
    )"
  >
    <slot />
  </label>
</template>
