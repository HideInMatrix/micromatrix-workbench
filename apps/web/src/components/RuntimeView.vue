<script setup lang="ts">
import RuntimeEditor from './services/RuntimeEditor.vue'
import { useRuntimeManager } from '../composables/useRuntimeManager'
import { Button } from '@/components/ui/button'

const manager = useRuntimeManager()
</script>

<template>
  <section class="grid gap-5">
    <header class="flex min-h-8 items-center justify-between gap-4">
      <div>
        <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">Runtime</h1>
        <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">
          应用启动只加载配置；点击启动后才运行 Pi Runtime 与公网隧道。
        </p>
      </div>
    </header>

    <div class="grid grid-cols-1 gap-2">
      <div class="min-h-28 rounded-lg bg-card p-4">
        <span class="block text-xs leading-5 text-muted-foreground">运行状态</span>
        <strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em]">
          {{ manager.ready.value ? (manager.running.value ? '运行中' : '已停止') : '—' }}
        </strong>
        <small
          :class="[
            'mt-1 block text-[11px] leading-4',
            manager.runtime.value?.exit_reason ? 'text-destructive' : 'text-muted-foreground',
          ]"
        >{{ manager.runtime.value?.exit_reason || 'Pi Agent MCP 本地执行服务' }}</small>
      </div>
    </div>

    <div v-if="!manager.ready.value" class="flex min-h-72 flex-col items-center justify-center gap-3 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
      <template v-if="manager.initializationError.value">
        <p role="alert" class="max-w-xl whitespace-pre-wrap text-center text-destructive">{{ manager.initializationError.value }}</p>
        <p>Runtime 与 Tunnel 尚未启动。</p>
        <Button variant="outline" size="sm" @click="manager.initialize">重新加载配置</Button>
      </template>
      <span v-else>{{ manager.initializing.value ? '正在加载配置（不会启动 Runtime）…' : '等待本地控制服务…' }}</span>
    </div>

    <RuntimeEditor
      v-else
      v-model:draft="manager.draft.value"
      v-model:tunnel-token-visible="manager.tunnelTokenVisible.value"
      :locked="manager.locked.value"
      :busy="manager.busy.value"
      :lifecycle-busy="manager.lifecycleBusy.value"
      :selected-running="manager.running.value"
      :copied-url="manager.copiedUrl.value"
      :runtime-url="manager.runtimeUrl.value"
      :network-providers="manager.networkProviders.value"
      :oauth-password-visible="manager.oauthPasswordVisible.value"
      @choose-workspace="manager.chooseWorkspace"
      @toggle-o-auth-password="manager.oauthPasswordVisible.value = !manager.oauthPasswordVisible.value"
      @copy-url="manager.copyUrl"
      @save="manager.saveRuntime"
      @toggle-running="manager.toggleRunning"
    />
  </section>
</template>
