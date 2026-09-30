<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Puzzle } from '@lucide/vue'
import { Switch } from '@/components/ui/switch'
import { desktopApi } from '../../api/desktop'
import type { BodyPluginDto } from '../../types'

const props = defineProps<{ locked: boolean }>()
const plugins = ref<BodyPluginDto[]>([])
const busy = ref('')

async function refresh() {
  plugins.value = await desktopApi.listBodyPlugins()
}

async function toggle(plugin: BodyPluginDto, enabled: boolean) {
  if (props.locked || plugin.required || busy.value) return
  busy.value = plugin.id
  try {
    await desktopApi.setBodyPluginEnabled(plugin.id, enabled)
    await refresh()
    toast.success(`${plugin.name} 已${enabled ? '启用' : '停用'}。`)
  } catch (reason) {
    toast.error(reason instanceof Error ? reason.message : String(reason))
  } finally {
    busy.value = ''
  }
}

onMounted(() => void refresh().catch(reason => toast.error(reason instanceof Error ? reason.message : String(reason))))
</script>

<template>
  <section class="grid gap-3 text-xs" aria-label="执行插件">
    <header class="flex items-center gap-2">
      <Puzzle :size="14" class="text-muted-foreground" />
      <h3 class="m-0 text-xs font-medium">执行插件</h3>
    </header>
    <div class="overflow-hidden rounded-lg border border-border bg-background">
      <div v-for="plugin in plugins" :key="plugin.id" class="flex items-center justify-between gap-3 border-b border-border px-3 py-2.5 last:border-b-0">
        <div class="grid gap-0.5">
          <span class="font-medium">{{ plugin.name }}</span>
          <code class="text-[10px] text-muted-foreground">{{ plugin.id }}</code>
        </div>
        <Switch
          :model-value="plugin.enabled"
          :disabled="locked || plugin.required || Boolean(busy)"
          :aria-label="`${plugin.enabled ? '关闭' : '开启'} ${plugin.name}`"
          @update:model-value="toggle(plugin, $event)"
        />
      </div>
    </div>
    <p v-if="locked" class="m-0 text-[11px] text-muted-foreground">停止 Runtime 后才能切换执行插件。</p>
  </section>
</template>
