<script setup lang="ts">
import { computed, type HTMLAttributes, type ButtonHTMLAttributes } from 'vue'
import { Primitive, type PrimitiveProps } from 'reka-ui'
import { cn } from '@/lib/utils'
import { buttonVariants, type ButtonVariants } from '.'

// Vue's SFC runtime-prop extractor cannot walk Reka UI's flattened declaration
// bundle. Keep inheritance for typing, but declare runtime-consumed props here.
interface Props extends /* @vue-ignore */ ButtonHTMLAttributes {
  // Explicit declarations are required for Vue's runtime prop extraction.
  // Without these, Primitive falls back to a div instead of a native button.
  as?: Exclude<PrimitiveProps['as'], undefined>
  asChild?: boolean
  variant?: ButtonVariants['variant']
  size?: ButtonVariants['size']
  class?: HTMLAttributes['class']
}

const props = withDefaults(defineProps<Props>(), {
  as: 'button',
  asChild: false,
})

// Keep semantic foreground colors on the rendered element. The packaged
// UnoCSS output currently keeps bg-primary but can omit foreground utilities
// declared only inside CVA strings, which makes primary buttons unreadable.
const semanticForeground = computed(() => {
  const variant = props.variant ?? 'default'
  if (variant === 'default') return 'oklch(var(--primary-foreground))'
  if (variant === 'secondary') return 'oklch(var(--secondary-foreground))'
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
