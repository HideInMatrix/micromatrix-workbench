<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'
import {
  SwitchRoot,
  SwitchThumb,
  type SwitchRootEmits,
  type SwitchRootProps,
  useForwardPropsEmits,
} from 'reka-ui'
import { cn } from '@/lib/utils'

interface Props extends SwitchRootProps {
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()
const emits = defineEmits<SwitchRootEmits>()

const delegatedProps = computed(() => {
  const { class: _, ...delegated } = props
  return delegated
})

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <SwitchRoot
    data-slot="switch"
    v-bind="forwarded"
    :class="cn(
      'peer inline-flex h-[1.15rem] w-8 shrink-0 cursor-pointer items-center justify-start gap-0 rounded-full border border-transparent shadow-xs transition-all outline-none',
      'data-[state=checked]:bg-primary data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-input/80',
      'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50',
      'disabled:cursor-not-allowed disabled:opacity-50',
      props.class,
    )"
  >
    <SwitchThumb
      data-slot="switch-thumb"
      class="pointer-events-none block size-4 rounded-full bg-background shadow-sm ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0 dark:data-[state=unchecked]:bg-foreground dark:data-[state=checked]:bg-primary-foreground"
    />
  </SwitchRoot>
</template>
