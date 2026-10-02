<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { desktopApi } from '../api/desktop'
import { useAppUpdater } from '../composables/useAppUpdater'
import AboutView from './AboutView.vue'

const version = ref('')
const updater = useAppUpdater()
onMounted(async () => {
  try {
    version.value = await desktopApi.appVersion()
  } catch (error) {
    toast.error(error instanceof Error ? error.message : String(error))
  }
})
</script>

<template>
  <div class="grid gap-4">
    <AboutView :version="version" :update="updater.state" :native="updater.native" :busy="updater.busy.value" :progress="updater.progress.value" @check="updater.check" @install="updater.install" @restart="updater.restart" />
  </div>
</template>
