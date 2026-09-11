<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'
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
  permissionMenuOpen,
  activePermissionRequest,
  isToolchainRegistration,
  isBrowserControl,
  isBrowserObserve,
  isDesktopControl,
  isDesktopObserve,
  isDesktopPermission,
  hasDesktopSession,
  canRememberDesktopApplication,
  isHostIdentityUse,
  isHostManage,
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

      <p v-if="isToolchainRegistration" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">此授权会保存到当前 Profile，供后续调用及重启后使用。注册阶段不会执行该工具，只冻结程序路径、只读范围和文件指纹；文件或路径变化后需重新确认。可在服务设置中移除注册。</p>
      <p v-else-if="isDesktopControl" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">此权限只针对当前 desktop 调用中已明确选择的目标窗口，用于鼠标、键盘、滚动或拖拽。Workbench 的应用授权与 macOS 辅助功能权限彼此独立；未获得系统权限时本次操作仍会在 Host 侧失败。</p>
      <p v-else-if="isDesktopObserve" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">此权限只针对当前 desktop 调用中已明确选择的目标窗口，用于获取窗口图像和可用的辅助功能信息。它不会授予键盘或鼠标控制，也不会把屏幕访问扩大到其他未绑定窗口。</p>
      <p v-else-if="isBrowserControl" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">Workbench Desktop Host 会创建独立临时浏览器 Profile，并通过本机 CDP 控制该 Session；不会复用你的日常浏览器 Cookie、扩展或登录 Profile。Session 关闭或 MCP Server 停止后会自动回收。</p>
      <p v-else-if="isBrowserObserve" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">此权限只允许读取 Workbench 隔离浏览器 Session 的截图与结构化页面信息，不授予导航、点击、输入、Host Identity 或 Host 管理权限。</p>
      <p v-else-if="isHostIdentityUse" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">Workbench Desktop Host 将在宿主用户身份上下文中执行这一条完全相同的已注册程序调用。不会把宿主环境或凭据作为 Tool Result 返回给 AI；授权只绑定当前 executable、参数、Workspace 与调用。</p>
      <p v-else-if="isHostManage" class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">此权限只允许重启 Workbench 自有 Host Worker。它不能指定任意 PID、应用或系统服务，也不会继承 Browser 控制权限。</p>
      <p v-else class="mt-3 mb-0 text-[10px] leading-[15px] text-muted-foreground">“仅允许本次”只作用于当前调用；“本次服务会话全部允许”在当前 MCP Server 停止或重启前，对同一已认证客户端自动放行可临时授权的权限。Workspace 边界和不可临时提升的系统限制仍然生效。</p>

      <footer class="mt-4 flex justify-end gap-2">
        <Button variant="outline" size="sm" class="min-w-[88px]" :disabled="permissionResponding" @click="respondPermission('deny')">拒绝</Button>
        <Button v-if="isToolchainRegistration" size="sm" :disabled="permissionResponding" @click="respondPermission('remember')">允许并记住此 Profile</Button>
        <div v-else-if="isDesktopPermission" class="flex gap-2">
          <Button variant="outline" class="min-w-[104px]" size="sm" :disabled="permissionResponding" @click="respondPermission('once')">仅允许本次</Button>
          <Button v-if="hasDesktopSession" class="min-w-[128px]" size="sm" :disabled="permissionResponding" @click="respondPermission('desktop_session')">允许本次桌面会话</Button>
          <Button v-if="canRememberDesktopApplication" class="min-w-[128px]" size="sm" :disabled="permissionResponding" @click="respondPermission('remember_app')">始终允许此应用</Button>
        </div>
        <Button v-else-if="isHostIdentityUse || isHostManage || isBrowserControl || isBrowserObserve" class="min-w-[104px]" size="sm" :disabled="permissionResponding" @click="respondPermission('once')">仅允许本次</Button>
        <div v-else class="relative inline-flex">
          <Button class="min-w-[104px] !rounded-r-none !rounded-l-[7px]" size="sm" :disabled="permissionResponding" @click="respondPermission('once')">仅允许本次</Button>
          <Button
            class="w-[34px] min-w-0 !rounded-l-none !rounded-r-[7px] border-l border-l-white/20 px-0"
            size="sm"
            :disabled="permissionResponding"
            title="更多授权方式"
            aria-label="更多授权方式"
            @click="permissionMenuOpen = !permissionMenuOpen"
          >
            <ChevronDown :size="16" />
          </Button>
          <div v-if="permissionMenuOpen" class="absolute right-0 bottom-[calc(100%+8px)] z-40 w-[250px] rounded-lg border border-border bg-background p-[5px] shadow-[0_14px_36px_rgb(0_0_0/0.18)]">
            <button
              class="flex w-full min-w-0 flex-col items-start gap-0.5 rounded-md border-0 bg-transparent px-2.5 py-[9px] text-left text-foreground hover:bg-secondary"
              type="button"
              @click="respondPermission('session')"
            >
              <strong class="text-[11px] leading-4 font-semibold">本次服务会话全部允许</strong>
              <span class="text-[9px] leading-[14px] text-muted-foreground">直到当前 MCP Server 停止或重启</span>
            </button>
          </div>
        </div>
      </footer>
    </section>
  </div>
</template>
