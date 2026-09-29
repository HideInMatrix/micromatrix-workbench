<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  Boxes,
  Info,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Server,
} from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import type { AppRouteName } from '../router'

defineProps<{ updateAvailable: boolean }>()

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

onMounted(() => {
  try {
    collapsed.value = window.localStorage.getItem('app-sidebar-collapsed') === '1'
  } catch {
    collapsed.value = false
  }
})

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  try {
    window.localStorage.setItem('app-sidebar-collapsed', collapsed.value ? '1' : '0')
  } catch {
    // Keep the in-memory state if WebView storage is unavailable.
  }
}

function navClass(name: AppRouteName): string[] {
  const active = name === 'plugins'
    ? String(route.name ?? '').startsWith('plugins')
    : route.name === name
  return [
    'group w-full text-xs font-normal',
    collapsed.value ? 'justify-center px-0' : 'justify-start gap-2 px-2.5',
    active
      ? 'bg-secondary text-foreground'
      : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
  ]
}
</script>

<template>
  <aside
    :class="[
      'flex flex-none flex-col border-r border-sidebar-border bg-sidebar py-5 text-sidebar-foreground transition-[width] duration-200',
      collapsed ? 'w-16 px-2' : 'w-60 px-3',
    ]"
  >
    <div :class="['flex min-h-8 items-center gap-2', collapsed ? 'justify-center' : 'justify-between px-1.5']">
      <div v-if="!collapsed" class="flex min-w-0 items-center gap-2.5">
        <div class="grid size-9 flex-none place-items-center rounded-md border border-sidebar-border bg-background/40">
          <img src="/workbench-mark.svg" alt="" class="size-6 dark:invert" />
        </div>
      </div>
      <Button v-if="!collapsed" variant="ghost" size="icon" class="h-7 w-7" title="收起侧边栏" @click="toggleCollapsed">
        <PanelLeftClose :size="15" />
      </Button>
      <Button
        v-else
        variant="ghost"
        size="icon"
        class="h-8 w-8"
        title="展开侧边栏"
        aria-label="展开侧边栏"
        aria-controls="app-sidebar-navigation"
        :aria-expanded="!collapsed"
        @click="toggleCollapsed"
      >
        <PanelLeftOpen :size="16" />
      </Button>
    </div>

    <nav id="app-sidebar-navigation" class="mt-5 grid gap-1" aria-label="主导航">
      <Button variant="ghost" size="sm" :class="navClass('work')" :title="collapsed ? 'Work' : undefined" @click="router.push({ name: 'work' })">
        <Server class="flex-none" :size="16" :stroke-width="1.8" />
        <span v-if="!collapsed" class="leading-none">Work</span>
      </Button>
      <Button variant="ghost" size="sm" :class="navClass('plugins')" :title="collapsed ? '插件' : undefined" @click="router.push({ name: 'plugins' })">
        <Boxes class="flex-none" :size="16" :stroke-width="1.8" />
        <span v-if="!collapsed" class="leading-none">插件</span>
      </Button>
      <Button variant="ghost" size="sm" :class="navClass('logs')" :title="collapsed ? '运行日志' : undefined" @click="router.push({ name: 'logs' })">
        <ScrollText class="flex-none" :size="16" :stroke-width="1.8" />
        <span v-if="!collapsed" class="leading-none">运行日志</span>
      </Button>
    </nav>

    <div class="mt-auto border-t border-sidebar-border pt-4">
      <Button
        variant="ghost"
        size="sm"
        :class="[...navClass('about'), 'relative']"
        :title="updateAvailable ? '关于 · 有新版本' : collapsed ? '关于' : undefined"
        :aria-label="updateAvailable ? '关于，有新版本' : '关于'"
        @click="router.push({ name: 'about' })"
      >
        <Info class="flex-none" :size="16" :stroke-width="1.8" />
        <span v-if="!collapsed" class="leading-none">关于</span>
        <span v-if="updateAvailable" :class="['size-1.5 rounded-full bg-destructive', collapsed ? 'absolute top-1 right-1' : 'ml-auto']" aria-hidden="true" />
      </Button>
    </div>
  </aside>
</template>
