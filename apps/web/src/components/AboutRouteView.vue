<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { desktopApi } from '../api/desktop'
import AboutView from './AboutView.vue'

const version = ref('')
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
    <AboutView :version="version" />
  </div>
</template>
