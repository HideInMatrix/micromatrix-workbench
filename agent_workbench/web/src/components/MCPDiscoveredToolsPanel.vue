<script setup lang="ts">
import type { MCPDiscoveredToolDto } from '../types'

defineProps<{ tools: MCPDiscoveredToolDto[] }>()
</script>

<template>
  <div class="grid gap-2">
    <div class="flex items-center justify-between">
      <span class="text-[11px] font-medium">已发现工具</span>
      <span class="text-[10px] text-muted-foreground">{{ tools.length }} 个工具</span>
    </div>
    <div class="max-h-64 overflow-y-auto rounded-md border border-border bg-background">
      <div v-for="tool in tools" :key="tool.name" class="border-b border-border px-3 py-2 last:border-b-0">
        <div class="font-mono text-[11px] font-medium">{{ tool.name }}</div>
        <div v-if="tool.description" class="mt-0.5 text-[10px] leading-4 text-muted-foreground">{{ tool.description }}</div>
      </div>
      <div v-if="!tools.length" class="px-3 py-6 text-center text-[10px] text-muted-foreground">
        保存连接后点击“发现工具”。
      </div>
    </div>
  </div>
</template>
