<script setup lang="ts">
import type { HTMLAttributes, ButtonHTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

interface Props extends /* @vue-ignore */ ButtonHTMLAttributes { class?: HTMLAttributes['class']; disabled?: boolean }
const props = defineProps<Props>()
</script>

<template>
  <button
    type="button"
    data-slot="input-group-button"
    :disabled="props.disabled"
    :class="cn(
      'flex h-full w-8 shrink-0 items-center justify-center border-0 bg-transparent text-muted-foreground outline-none transition-colors hover:bg-secondary/70 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/20 disabled:pointer-events-none disabled:opacity-50',
      props.class,
    )"
  >
    <slot />
  </button>
</template>
