<script setup lang="ts">
import RuntimeEditor from './services/RuntimeEditor.vue'
import { useRuntimeManager } from '../composables/useRuntimeManager'
import { Button } from '@/components/ui/button'

const manager = useRuntimeManager()
</script>

<template>
  <section class="grid w-full max-w-[840px] gap-5">
    <header class="flex min-h-8 items-center justify-between gap-4">
      <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">Runtime</h1>
      <span role="status" :class="['rounded-full px-2.5 py-1 text-xs font-medium', manager.running.value ? 'bg-success/10 text-success' : 'bg-secondary text-muted-foreground']">
        {{ manager.ready.value ? (manager.running.value ? '运行中' : '已停止') : '加载中' }}
      </span>
    </header>
    <p v-if="manager.runtime.value?.exit_reason" role="alert" class="whitespace-pre-wrap text-xs text-destructive">{{ manager.runtime.value.exit_reason }}</p>

    <div v-if="!manager.ready.value" class="flex min-h-72 flex-col items-center justify-center gap-3 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
      <template v-if="manager.initializationError.value">
        <p role="alert" class="max-w-xl whitespace-pre-wrap text-center text-destructive">{{ manager.initializationError.value }}</p>
        <p>Runtime 与 Tunnel 尚未启动。</p>
        <Button variant="outline" size="sm" @click="manager.initialize">重新加载配置</Button>
      </template>
      <span v-else>{{ manager.initializing.value ? '正在加载配置（不会启动 Runtime）…' : '等待本地控制服务…' }}</span>
    </div>

    <RuntimeEditor
      v-if="manager.ready.value"
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
