<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import {
  PopoverContent,
  PopoverPortal,
  PopoverRoot,
  PopoverTrigger,
} from 'reka-ui'
import { cn } from '@/lib/utils'

const props = withDefaults(defineProps<{
  contentClass?: HTMLAttributes['class']
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  sideOffset?: number
}>(), {
  align: 'end',
  side: 'bottom',
  sideOffset: 6,
})
</script>

<template>
  <PopoverRoot>
    <PopoverTrigger as-child>
      <slot name="trigger" />
    </PopoverTrigger>

    <PopoverPortal>
      <PopoverContent
        :align="props.align"
        :side="props.side"
        :side-offset="props.sideOffset"
        :class="cn(
          'z-50 rounded-lg border border-border bg-popover shadow-lg outline-none',
          props.contentClass,
        )"
      >
        <slot />
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
