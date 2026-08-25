<script setup lang="ts">
import { Button } from '@/components/ui/button'
import type { GatewayDiagnosticDto } from '../../types'
import { diagnosticErrorText } from '../../composables/useServiceManager'

defineProps<{
  diagnostic: GatewayDiagnosticDto | null
  busy: boolean
}>()

const emit = defineEmits<{ test: [] }>()
</script>

<template>
  <section class="mt-4 grid gap-3 rounded-lg border border-border px-3 py-[11px]">
    <div class="flex items-center gap-3">
      <div class="grid min-w-0 flex-1 gap-[3px]">
        <strong>公网 E2E 自检</strong>
        <span class="text-[11px] text-muted-foreground">多 Workspace 服务会验证每个 Path 对应的 Runtime、OAuth metadata 与授权码换 Token。</span>
      </div>
      <Button variant="outline" size="sm" :disabled="busy" @click="emit('test')">开始自检</Button>
      <span v-if="diagnostic" :class="diagnostic.ok ? 'text-[#67C23A]' : 'text-[#F56C6C]'">
        {{ diagnostic.ok ? '全部通过' : `${diagnostic.profiles.filter(profile => !profile.ok).length} 个 Profile 失败` }}
      </span>
    </div>

    <div v-if="diagnostic && !diagnostic.ok" class="grid gap-2 border-t border-border pt-3">
      <article
        v-for="profile in diagnostic.profiles.filter(item => !item.ok)"
        :key="profile.server_id"
        class="rounded-md bg-destructive/5 px-3 py-2.5"
      >
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <strong>{{ profile.name }}</strong>
          <code class="text-[11px] text-muted-foreground">{{ profile.instance_path || '/' }}</code>
        </div>
        <ul class="mt-2 grid gap-1 pl-4 text-[11px] leading-5 text-destructive">
          <li v-for="(error, index) in profile.errors" :key="`${profile.server_id}:${index}`">{{ diagnosticErrorText(error) }}</li>
          <li v-if="!profile.errors.length">未返回具体错误，请查看运行日志。</li>
        </ul>
      </article>
    </div>
  </section>
</template>
