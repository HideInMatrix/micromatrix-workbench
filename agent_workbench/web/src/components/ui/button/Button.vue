<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'
import { Primitive, type PrimitiveProps } from 'reka-ui'
import { cn } from '@/lib/utils'
import { buttonVariants, type ButtonVariants } from '.'

interface Props extends PrimitiveProps {
  variant?: ButtonVariants['variant']
  size?: ButtonVariants['size']
  class?: HTMLAttributes['class']
}

const props = withDefaults(defineProps<Props>(), {
  as: 'button',
})

// Keep semantic foreground colors on the rendered element. The packaged
// UnoCSS output currently keeps bg-primary but can omit foreground utilities
// declared only inside CVA strings, which makes primary buttons unreadable.
const semanticForeground = computed(() => {
  const variant = props.variant ?? 'default'
  if (variant === 'default') return 'var(--primary-foreground)'
  if (variant === 'secondary') return 'var(--secondary-foreground)'
  if (variant === 'destructive') return 'white'
  return ''
})
</script>

<template>
  <Primitive
    data-slot="button"
    :as="props.as"
    :as-child="props.asChild"
    :class="cn(buttonVariants({ variant: props.variant, size: props.size }), props.class)"
    :style="semanticForeground ? { color: semanticForeground } : undefined"
  >
    <slot />
  </Primitive>
</template>
