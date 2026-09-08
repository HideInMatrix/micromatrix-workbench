<script setup lang="ts">
import { desktopApi } from '../api/desktop'
import { useAppUpdates } from '../composables/useAppUpdates'
import AboutView from './AboutView.vue'

const {
  version, release, checkingUpdate, updateProxyPrefix, savingUpdateProxy, errorMessage,
  updateStatus, installError, installBusy, lastCheckedAt,
  checkUpdate, saveUpdateProxy, startUpdate, prepareInstall,
} = useAppUpdates()
</script>

<template>
  <div class="grid gap-4">
    <div
      v-if="errorMessage || installError"
      role="alert"
      class="flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
    >
      <span>{{ errorMessage || installError }}</span>
      <button class="border-0 bg-transparent text-lg leading-none text-inherit" aria-label="关闭错误提示" @click="errorMessage = ''; installError = ''">×</button>
    </div>
    <AboutView
      :version="version"
      :release="release"
      :checking="checkingUpdate"
      :update-status="updateStatus"
      :update-proxy-prefix="updateProxyPrefix"
      :saving-proxy="savingUpdateProxy"
      :operation-busy="installBusy"
      :last-checked-at="lastCheckedAt"
      @check="checkUpdate(true)"
      @update="startUpdate"
      @install="prepareInstall"
      @save-proxy="saveUpdateProxy"
      @open="desktopApi.openExternal"
    />
  </div>
</template>
