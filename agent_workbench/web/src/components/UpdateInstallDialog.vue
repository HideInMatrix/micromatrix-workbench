<script setup lang="ts">
import { DialogRoot, DialogPortal, DialogOverlay, DialogContent, DialogTitle, DialogDescription } from 'reka-ui'
import { Button } from '@/components/ui/button'
import type { UpdateInstallImpactDto } from '../types'

defineProps<{ impact: UpdateInstallImpactDto | null; busy: boolean }>()
const emit = defineEmits<{ cancel: []; confirm: [] }>()
</script>

<template>
  <DialogRoot :open="impact !== null" @update:open="!$event && emit('cancel')">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-[900] bg-black/40 backdrop-blur-[2px]" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-[901] w-[min(460px,calc(100%-32px))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-background p-5 shadow-xl"
        @escape-key-down="busy && $event.preventDefault()"
        @pointer-down-outside="$event.preventDefault()"
      >
        <DialogTitle class="m-0 text-base font-semibold">安装 {{ impact?.version }} 并重启</DialogTitle>
        <DialogDescription class="mt-2 text-xs leading-5 text-muted-foreground">
          安装会退出当前程序，完成后重新打开。请先保存工作，并确认运行中的任务可以中断。
        </DialogDescription>
        <div v-if="impact?.services.length" class="mt-4 rounded-md border border-border bg-secondary p-3">
          <p class="m-0 text-xs font-medium">将停止以下服务：</p>
          <ul class="mt-2 mb-0 max-h-48 overflow-auto pl-4 text-xs leading-6">
            <li v-for="service in impact.services" :key="service.id">{{ service.name }}</li>
          </ul>
          <p class="mt-2 mb-0 text-[11px] text-muted-foreground">服务中的 Profile 和连接会一并停止，重启后需手动启动。</p>
        </div>
        <p v-else class="mt-4 text-xs text-muted-foreground">当前没有运行中的服务。</p>
        <div class="mt-5 flex justify-end gap-2">
          <Button variant="outline" size="sm" :disabled="busy" @click="emit('cancel')">暂不安装</Button>
          <Button size="sm" :disabled="busy" @click="emit('confirm')">{{ busy ? '正在安装…' : '确认安装并重启' }}</Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
