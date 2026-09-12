<script setup lang="ts">
import { Plus } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  workEnabled,
  workName,
  workPort,
  workRunning,
  type WorkItem,
} from './serviceModels'

defineProps<{
  works: WorkItem[]
  selectedKey: string
  togglingId: string
}>()

const emit = defineEmits<{
  create: []
  select: [key: string]
  toggle: [work: WorkItem, enabled: boolean]
}>()
</script>

<template>
  <aside class="overflow-hidden rounded-[10px] border border-border bg-card">
    <div class="flex items-center justify-between gap-3 border-b border-border p-3.5">
      <div class="grid gap-[3px]">
        <strong>Work</strong>
        <span class="text-[11px] text-muted-foreground">Switch 表示随应用自动启动</span>
      </div>
      <Button variant="outline" size="sm" class="min-h-[30px] px-2.5" @click="emit('create')">
        <Plus :size="14" /> 新建
      </Button>
    </div>

    <div
      v-for="work in works"
      :key="work.key"
      :class="[
        'flex min-h-[64px] items-center gap-2.5 border-b border-border px-3.5 py-2.5 hover:bg-secondary',
        { 'bg-secondary': work.key === selectedKey },
      ]"
    >
      <button
        type="button"
        class="flex min-w-0 flex-1 items-center gap-2.5 border-0 bg-transparent p-0 text-left text-inherit"
        @click="emit('select', work.key)"
      >
        <span :class="['h-2 w-2 shrink-0 rounded-full', workRunning(work) ? 'bg-[#67C23A]' : 'bg-[#909399]']" />
        <span class="grid min-w-0 flex-1 justify-items-start gap-[3px] text-left">
          <strong class="w-full truncate text-left">{{ workName(work) }}</strong>
          <small class="w-full truncate text-left text-[11px] text-muted-foreground">
            {{ work.server.network.public_url || `:${workPort(work)}` }}
          </small>
        </span>
      </button>

      <div class="relative shrink-0" @click.stop>
        <Switch
          :model-value="workEnabled(work)"
          :aria-label="`${workEnabled(work) ? '关闭' : '开启'} ${workName(work)} 随应用自动启动`"
          :title="workEnabled(work) ? '关闭随应用自动启动' : '开启随应用自动启动'"
          :disabled="Boolean(togglingId)"
          @update:model-value="emit('toggle', work, $event)"
        />

      </div>
    </div>

    <div v-if="!works.length" class="flex min-h-[250px] flex-col items-center justify-center px-5 py-[42px] text-center text-muted-foreground">
      尚未创建 Work
    </div>
  </aside>
</template>
