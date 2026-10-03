<script setup lang="ts">
import { Button } from '@/components/ui/button'
import type { UpdateState } from '../api/updateController'
defineProps<{ version: string; update: UpdateState; native: boolean; busy: boolean; progress: number | null }>()
defineEmits<{ check: []; install: []; restart: [] }>()
</script>

<template>
  <section class="w-full max-w-[700px]">
    <div>
      <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">关于</h1>
      <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">应用与运行时信息</p>
    </div>
    <div class="mt-5 max-w-[430px] overflow-hidden rounded-lg border border-border bg-popover p-5 shadow-sm">
      <div class="flex justify-between gap-4 border-b border-border py-2.5 text-[11px]"><span>应用名称</span><strong>micromatrix agent</strong></div>
      <div class="flex justify-between gap-4 border-b border-border py-2.5 text-[11px]"><span>当前版本</span><strong>{{ version || '—' }}</strong></div>
      <div class="flex justify-between gap-4 border-b border-border py-2.5 text-[11px]"><span>执行核心</span><strong>Pi Agent</strong></div>
      <div class="mt-4 space-y-3 text-xs" aria-live="polite">
        <template v-if="native">
          <p class="text-muted-foreground">启动后自动检查正式版更新，每 6 小时复查；发现新版自动下载、安装并重启，无需确认。重启后不会自动启动 Runtime。</p>
          <p v-if="update.phase === 'checking'">正在检查更新…</p>
          <p v-else-if="update.phase === 'current'">当前已是最新正式版。</p>
          <p v-else-if="update.version">新版本：<strong>{{ update.version }}</strong></p>
          <p v-if="update.phase === 'downloading'">正在下载并验证签名：{{ progress === null ? `${Math.round(update.downloaded / 1024)} KB` : `${progress}%` }}</p>
          <p v-if="update.phase === 'installing'">正在停止 Runtime / Tunnel 并安装更新…</p>
          <p v-if="update.phase === 'installed'">更新已安装，重启应用后生效。</p>
          <p v-if="update.error" class="text-destructive break-words">更新失败：{{ update.error }}</p>
          <div class="flex flex-wrap gap-2">
            <Button v-if="update.phase !== 'installed'" size="sm" variant="outline" :disabled="busy" @click="$emit('check')">检查更新</Button>
            <Button v-if="update.version && update.phase === 'error'" size="sm" :disabled="busy" @click="$emit('install')">重试更新并重启</Button>
            <Button v-if="update.phase === 'installed'" size="sm" @click="$emit('restart')">重启应用</Button>
          </div>
          <p v-if="update.version" class="text-muted-foreground">下载及签名验证成功后自动停止 Runtime 与 Tunnel，再安装并重启。系统需要的管理员授权仍须完成；重启后需手动启动 Runtime。</p>
          <details v-if="update.notes"><summary class="cursor-pointer">版本说明</summary><pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-sans text-[11px]">{{ update.notes }}</pre></details>
        </template>
        <p v-else class="text-muted-foreground">Web 页面不支持安装桌面更新，请在桌面应用中检查更新。</p>
      </div>
      <small class="mt-4 block text-[10px] text-muted-foreground">Copyright © micromatrix.org</small>
    </div>
  </section>
</template>
