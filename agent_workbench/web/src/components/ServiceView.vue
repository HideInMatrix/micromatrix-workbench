<script setup lang="ts">
import ServiceEditor from './services/ServiceEditor.vue'
import ServiceListPanel from './services/ServiceListPanel.vue'
import { useServiceManager } from '../composables/useServiceManager'

const manager = useServiceManager()
</script>

<template>
  <section class="grid gap-5">
    <header class="flex min-h-8 items-center justify-between gap-4">
      <div>
        <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">服务</h1>
        <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">
          一个服务管理一个公网入口；Profile 配置与运行模式分离，由顶部滑块明确决定本次启用单 Workspace 还是多 Workspace。
        </p>
      </div>
    </header>

    <div v-if="manager.errorMessage.value" class="sticky top-2 z-30 mb-4 flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
      <span>{{ manager.errorMessage.value }}</span>
      <button class="border-0 bg-transparent text-lg leading-none text-inherit" @click="manager.errorMessage.value = ''">×</button>
    </div>

    <div class="grid grid-cols-1 gap-2 lg:grid-cols-3">
      <div class="min-h-28 rounded-lg bg-card p-4"><span class="block text-xs leading-5 text-muted-foreground">服务</span><strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em] tabular-nums">{{ manager.stats.value.services }}</strong><small class="mt-1 block text-[11px] leading-4 text-muted-foreground">统一公网入口</small></div>
      <div class="min-h-28 rounded-lg bg-card p-4"><span class="block text-xs leading-5 text-muted-foreground">正在运行</span><strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em] tabular-nums">{{ manager.stats.value.running }}</strong><small class="mt-1 block text-[11px] leading-4 text-muted-foreground">{{ manager.stats.value.services - manager.stats.value.running }} 个已停止</small></div>
      <div class="min-h-28 rounded-lg bg-card p-4"><span class="block text-xs leading-5 text-muted-foreground">Workspace</span><strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em] tabular-nums">{{ manager.stats.value.workspaces }}</strong><small class="mt-1 block text-[11px] leading-4 text-muted-foreground">主 Workspace + 子 Profile</small></div>
    </div>

    <div class="grid items-start gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <ServiceListPanel
        :services="manager.services.value"
        :selected-key="manager.selectedKey.value"
        @create="manager.createNew"
        @select="manager.selectService"
      />
      <ServiceEditor
        v-model:draft="manager.draft.value"
        v-model:tunnel-token-visible="manager.tunnelTokenVisible.value"
        :is-new="manager.isNew.value"
        :locked="manager.locked.value"
        :busy="manager.busy.value"
        :selected-running="manager.selectedRunning.value"
        :selected-is-starting="manager.selectedIsStarting.value"
        :copied-url="manager.copiedUrl.value"
        :diagnostic="manager.diagnostic.value"
        :show-diagnostic="manager.showDiagnostic.value"
        :is-root-profile="manager.isRootProfile"
        :profile-enabled="manager.profileEnabled"
        :runtime-url="manager.runtimeUrl"
        :is-o-auth-password-visible="manager.isOAuthPasswordVisible"
        @set-mode="manager.setMode"
        @add-profile="manager.addProfile"
        @remove-profile="manager.removeProfile"
        @choose-workspace="manager.chooseWorkspace"
        @toggle-o-auth-password="manager.toggleOAuthPassword"
        @copy-url="manager.copyUrl"
        @test="manager.testService"
        @delete="manager.deleteService"
        @save="manager.saveService"
        @toggle="manager.toggleService"
      />
    </div>
  </section>
</template>
