<script setup lang="ts">
import { Plus } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import {
  serviceMode,
  serviceName,
  servicePort,
  serviceProfileCount,
  serviceRunning,
  type ServiceItem,
} from './serviceModels'

defineProps<{
  services: ServiceItem[]
  selectedKey: string
}>()

const emit = defineEmits<{
  create: []
  select: [key: string]
}>()
</script>

<template>
  <aside class="overflow-hidden rounded-[10px] border border-border bg-card">
    <div class="flex items-center justify-between gap-3 border-b border-border p-3.5">
      <div class="grid gap-[3px]">
        <strong>服务</strong>
        <span class="text-[11px] text-muted-foreground">单入口，多 Workspace 可选</span>
      </div>
      <Button variant="outline" size="sm" class="min-h-[30px] px-2.5" @click="emit('create')">
        <Plus :size="14" /> 新建
      </Button>
    </div>

    <button
      v-for="service in services"
      :key="service.key"
      type="button"
      :class="[
        'flex min-h-[58px] w-full cursor-pointer items-center justify-start gap-2.5 border-0 border-b border-border bg-transparent px-3.5 py-2.5 text-left text-inherit hover:bg-secondary',
        { 'bg-secondary': service.key === selectedKey },
      ]"
      @click="emit('select', service.key)"
    >
      <span :class="['h-2 w-2 shrink-0 rounded-full', serviceRunning(service) ? 'bg-[#67C23A]' : 'bg-[#F56C6C]']" />
      <span class="grid min-w-0 flex-1 justify-items-start gap-[3px] text-left">
        <strong class="w-full truncate text-left">{{ serviceName(service) }}</strong>
        <small class="w-full truncate text-left text-[11px] text-muted-foreground">
          {{ serviceMode(service) === 'single' ? '单 Workspace' : '多 Workspace' }} · {{ serviceProfileCount(service) }} 个配置 · :{{ servicePort(service) }}
        </small>
      </span>
    </button>

    <div v-if="!services.length" class="flex min-h-[250px] flex-col items-center justify-center px-5 py-[42px] text-center text-muted-foreground">
      尚未创建服务
    </div>
  </aside>
</template>
