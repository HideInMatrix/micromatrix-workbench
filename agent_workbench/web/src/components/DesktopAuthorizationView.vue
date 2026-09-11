<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { desktopApi } from '@/api/desktop'
import { Button } from '@/components/ui/button'
import type { DesktopAuthorizationDto } from '@/types'

const rules = ref<DesktopAuthorizationDto[]>([])
const loading = ref(false)
const errorMessage = ref('')
const revokingId = ref('')
const stopping = ref(false)
const stopMessage = ref('')

const empty = computed(() => !loading.value && rules.value.length === 0)

function permissionLabel(permission: DesktopAuthorizationDto['permission']) {
  return permission === 'desktop_control' ? '观察并控制' : '仅观察'
}

function formatTime(value: number) {
  if (!value) return '—'
  return new Date(value * 1000).toLocaleString()
}

async function refresh() {
  loading.value = true
  errorMessage.value = ''
  try {
    rules.value = await desktopApi.listDesktopAuthorizations()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function revoke(rule: DesktopAuthorizationDto) {
  if (revokingId.value) return
  revokingId.value = rule.id
  errorMessage.value = ''
  try {
    const removed = await desktopApi.revokeDesktopAuthorization(rule.id)
    if (!removed) errorMessage.value = '该授权规则已不存在或已被撤销。'
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    revokingId.value = ''
  }
}

async function stopAllInput() {
  if (stopping.value) return
  stopping.value = true
  errorMessage.value = ''
  stopMessage.value = ''
  try {
    const result = await desktopApi.stopAllDesktopInput()
    stopMessage.value = result.requested
      ? `已向 ${result.requested} 个 Profile 发送停止指令，${result.stopped} 个当前 Host 已确认。`
      : '当前没有可发送停止指令的 Profile。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    stopping.value = false
  }
}

onMounted(() => void refresh())
</script>

<template>
  <section class="mx-auto w-full max-w-5xl">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="m-0 text-xl font-semibold text-foreground">桌面应用授权</h1>
        <p class="mt-1.5 mb-0 max-w-3xl text-xs leading-5 text-muted-foreground">
          管理“始终允许此应用”的 Workbench 授权。规则只匹配同一客户端主体、Profile、应用身份和权限范围；系统屏幕访问或辅助功能权限仍由操作系统独立控制。
        </p>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" :disabled="stopping" @click="stopAllInput">
          {{ stopping ? '停止中…' : '立即停止桌面输入' }}
        </Button>
        <Button variant="outline" size="sm" :disabled="loading" @click="refresh">刷新</Button>
      </div>
    </div>

    <div v-if="errorMessage" class="mt-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
      {{ errorMessage }}
    </div>
    <div v-if="stopMessage" class="mt-4 rounded-lg border border-border bg-secondary px-3 py-2.5 text-xs text-foreground">
      {{ stopMessage }}
    </div>

    <div v-if="loading && !rules.length" class="mt-5 rounded-lg border border-border bg-card px-4 py-6 text-xs text-muted-foreground">
      正在读取桌面授权规则…
    </div>

    <div v-else-if="empty" class="mt-5 rounded-lg border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
      当前没有持久桌面应用授权。首次桌面访问时可在授权弹窗中选择“始终允许此应用”。
    </div>

    <div v-else class="mt-5 grid gap-3">
      <article v-for="rule in rules" :key="rule.id" class="rounded-lg border border-border bg-card p-4">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <strong class="truncate text-sm font-semibold text-foreground">{{ rule.application_name || rule.application_id }}</strong>
              <span class="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">{{ permissionLabel(rule.permission) }}</span>
            </div>
            <div class="mt-2 grid gap-1 text-[11px] leading-4 text-muted-foreground">
              <span>Profile：{{ rule.server_name }}</span>
              <span class="break-all font-mono">应用身份：{{ rule.application_id }}</span>
              <span class="break-all font-mono">指纹：{{ rule.identity_fingerprint }}</span>
              <span>创建：{{ formatTime(rule.created_at) }} · 最近使用：{{ formatTime(rule.last_used_at) }}</span>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            class="flex-none"
            :disabled="Boolean(revokingId)"
            @click="revoke(rule)"
          >
            {{ revokingId === rule.id ? '撤销中…' : '撤销授权' }}
          </Button>
        </div>
      </article>
    </div>
  </section>
</template>
