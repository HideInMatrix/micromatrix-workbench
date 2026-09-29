<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { desktopApi } from '../api/desktop'
import AboutView from './AboutView.vue'

const version = ref('')
const errorMessage = ref('')

onMounted(async () => {
  try {
    version.value = await desktopApi.appVersion()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
})
</script>

<template>
  <div class="grid gap-4">
    <div
      v-if="errorMessage"
      role="alert"
      class="flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
    >
      <span>{{ errorMessage }}</span>
      <button class="border-0 bg-transparent text-lg leading-none text-inherit" aria-label="关闭错误提示" @click="errorMessage = ''">×</button>
    </div>
    <AboutView :version="version" />
  </div>
</template>
