<script setup lang="ts">
import { Switch } from '@/components/ui/switch'
import RuntimeEditor from './services/RuntimeEditor.vue'
import { useRuntimeManager } from '../composables/useRuntimeManager'

const manager = useRuntimeManager()
</script>

<template>
  <section class="grid gap-5">
    <header class="flex min-h-8 items-center justify-between gap-4">
      <div>
        <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">Runtime</h1>
        <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">
          当前桌面实例只管理一个 Pi Runtime；自动启动与当前进程启停相互独立。
        </p>
      </div>
    </header>

    <div v-if="manager.errorMessage.value" class="sticky top-2 z-30 mb-4 flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
      <span>{{ manager.errorMessage.value }}</span>
      <button class="border-0 bg-transparent text-lg leading-none text-inherit" @click="manager.errorMessage.value = ''">×</button>
    </div>

    <div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
      <div class="min-h-28 rounded-lg bg-card p-4">
        <span class="block text-xs leading-5 text-muted-foreground">运行状态</span>
        <strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em]">
          {{ manager.ready.value ? (manager.running.value ? '运行中' : '已停止') : '—' }}
        </strong>
        <small class="mt-1 block text-[11px] leading-4 text-muted-foreground">Pi Agent MCP 本地执行服务</small>
      </div>
      <div class="flex min-h-28 items-center justify-between gap-4 rounded-lg bg-card p-4">
        <div>
          <span class="block text-xs leading-5 text-muted-foreground">随应用自动启动</span>
          <strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em]">
            {{ manager.ready.value ? (manager.draft.value.enabled ? '已开启' : '已关闭') : '—' }}
          </strong>
          <small class="mt-1 block text-[11px] leading-4 text-muted-foreground">不改变 Runtime 当前运行状态</small>
        </div>
        <Switch
          :model-value="manager.draft.value.enabled"
          :disabled="!manager.ready.value || manager.enabling.value"
          aria-label="切换随应用自动启动"
          @update:model-value="manager.setEnabled"
        />
      </div>
    </div>

    <div v-if="!manager.ready.value" class="flex min-h-72 items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
      {{ manager.initializing.value ? '正在加载 Runtime…' : '等待 Runtime 数据…' }}
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
