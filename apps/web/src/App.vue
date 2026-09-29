<script setup lang="ts">
import { RouterView } from 'vue-router'
import { Button } from '@/components/ui/button'
import AppSidebar from './components/AppSidebar.vue'
import UpdateInstallDialog from './components/UpdateInstallDialog.vue'
import { provideAppUpdates } from './composables/useAppUpdates'
import { usePermissionRequests } from './composables/usePermissionRequests'

const { updateAvailable, installImpact, installing, cancelInstall, confirmInstall } = provideAppUpdates()
const {
  errorMessage,
  permissionResponding,
  activePermissionRequest,
  permissionArguments,
  permissionLabel,
  respondPermission,
} = usePermissionRequests()
</script>

<template>
  <div class="flex h-screen bg-background">
    <AppSidebar :update-available="updateAvailable" />

    <main class="min-w-0 flex-1 overflow-auto">
      <div class="mx-auto flex min-h-full w-full max-w-none flex-col px-3 py-4 max-[1050px]:px-2.5 max-[1050px]:py-3">
        <div
          v-if="errorMessage"
          class="sticky top-2 z-30 mb-4 flex items-center justify-between gap-3 rounded-[7px] border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
        >
          <span>{{ errorMessage }}</span>
          <button class="border-0 bg-transparent text-lg leading-none text-inherit" @click="errorMessage = ''">×</button>
        </div>

        <RouterView />
      </div>
    </main>
  </div>

  <UpdateInstallDialog :impact="installImpact" :busy="installing" @cancel="cancelInstall" @confirm="confirmInstall" />

  <div
    v-if="activePermissionRequest"
    class="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-6 backdrop-blur-[2px]"
  >
    <section
      class="max-h-[min(680px,calc(100vh-48px))] w-[min(560px,100%)] overflow-auto rounded-[10px] border border-border bg-background p-[18px] shadow-[0_18px_50px_rgb(0_0_0/0.2)]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="permission-dialog-title"
    >
      <header class="flex items-start justify-between gap-4">
        <div>
          <span class="text-[10px] leading-[14px] font-semibold text-destructive">需要授权</span>
          <h2 id="permission-dialog-title" class="mt-[3px] mb-0 text-[17px] leading-6">{{ permissionLabel(activePermissionRequest.permission) }}</h2>
        </div>
        <span class="max-w-[180px] flex-none overflow-hidden text-ellipsis whitespace-nowrap rounded-full bg-secondary px-[7px] py-[3px] text-[10px] leading-[15px] text-muted-foreground">{{ activePermissionRequest.server_name }}</span>
      </header>

      <p class="mt-3.5 mb-0 text-xs leading-[18px] text-foreground">{{ activePermissionRequest.reason }}</p>

      <dl class="mt-3.5 mb-0 grid grid-cols-2 gap-2">
        <div class="min-w-0 rounded-[7px] border border-border bg-secondary px-2.5 py-2">
          <dt class="text-[9px] leading-[13px] text-muted-foreground">工具</dt>
          <dd class="mt-0.5 mb-0 font-mono text-[11px] leading-4 text-foreground [overflow-wrap:anywhere]">{{ activePermissionRequest.tool_name }}</dd>
        </div>
        <div class="min-w-0 rounded-[7px] border border-border bg-secondary px-2.5 py-2">
          <dt class="text-[9px] leading-[13px] text-muted-foreground">权限</dt>
          <dd class="mt-0.5 mb-0 font-mono text-[11px] leading-4 text-foreground [overflow-wrap:anywhere]">{{ activePermissionRequest.permission }}</dd>
        </div>
      </dl>

      <div class="mt-3.5">
        <span class="text-[10px] leading-[15px] text-muted-foreground">本次调用参数（敏感字段已脱敏）</span>
        <pre class="mt-1.5 mb-0 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-[7px] border border-border bg-secondary p-2.5 text-[10px] leading-4 text-foreground [overflow-wrap:anywhere]">{{ permissionArguments }}</pre>
      </div>

      <p class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">“仅允许本次”只作用于当前调用；“本次服务会话允许”在 Runtime 停止或重启前自动放行同类权限。审批模式不是操作系统沙箱。</p>

      <footer class="mt-4 flex justify-end gap-2">
        <Button variant="outline" size="sm" class="min-w-[88px]" :disabled="permissionResponding" @click="respondPermission('deny')">拒绝</Button>
        <Button variant="outline" class="min-w-[104px]" size="sm" :disabled="permissionResponding" @click="respondPermission('once')">仅允许本次</Button>
        <Button class="min-w-[128px]" size="sm" :disabled="permissionResponding" @click="respondPermission('session')">本次服务会话允许</Button>
      </footer>
    </section>
  </div>
</template>
