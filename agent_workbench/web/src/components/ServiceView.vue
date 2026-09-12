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
        <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">Work</h1>
        <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">
          一个 Work 对应一个独立域名、一个 Runtime 和一个工作目录；Switch 只决定应用启动时是否自动启动，当前启停由按钮控制。
        </p>
      </div>
    </header>

    <div v-if="manager.errorMessage.value" class="sticky top-2 z-30 mb-4 flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
      <span>{{ manager.errorMessage.value }}</span>
      <button class="border-0 bg-transparent text-lg leading-none text-inherit" @click="manager.errorMessage.value = ''">×</button>
    </div>

    <div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
      <div class="min-h-28 rounded-lg bg-card p-4">
        <span class="block text-xs leading-5 text-muted-foreground">Work</span>
        <strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em] tabular-nums">{{ manager.stats.value.works }}</strong>
        <small class="mt-1 block text-[11px] leading-4 text-muted-foreground">独立域名与 Runtime</small>
      </div>
      <div class="min-h-28 rounded-lg bg-card p-4">
        <span class="block text-xs leading-5 text-muted-foreground">正在运行</span>
        <strong class="mt-2.5 block min-h-8 text-2xl leading-8 font-medium tracking-[-0.03em] tabular-nums">{{ manager.stats.value.running }}</strong>
        <small class="mt-1 block text-[11px] leading-4 text-muted-foreground">当前 Runtime 状态</small>
      </div>
    </div>

    <div class="grid items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <ServiceListPanel
        :works="manager.works.value"
        :selected-key="manager.selectedKey.value"
        :toggling-id="manager.togglingId.value"
        @create="manager.createNew"
        @select="manager.selectWork"
        @toggle="manager.toggleWork"
      />
      <ServiceEditor
        v-model:draft="manager.draft.value"
        v-model:tunnel-token-visible="manager.tunnelTokenVisible.value"
        :is-new="manager.isNew.value"
        :locked="manager.locked.value"
        :busy="manager.busy.value"
        :lifecycle-busy="manager.lifecycleBusy.value"
        :selected-running="manager.selectedRunning.value"
        :copied-url="manager.copiedUrl.value"
        :runtime-url="manager.runtimeUrl.value"
        :network-providers="manager.networkProviders.value"
        :oauth-password-visible="manager.oauthPasswordVisible.value"
        @choose-workspace="manager.chooseWorkspace"
        @toggle-o-auth-password="manager.oauthPasswordVisible.value = !manager.oauthPasswordVisible.value"
        @copy-url="manager.copyUrl"
        @delete="manager.deleteWork"
        @save="manager.saveWork"
        @toggle-running="manager.toggleRunning"
      />
    </div>
  </section>
</template>
