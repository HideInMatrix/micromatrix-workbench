<script setup lang="ts">
defineProps<{ version: string }>()
</script>

<template>
  <section class="w-full max-w-[700px]">
    <div>
      <h1 class="m-0 text-xl leading-7 font-medium tracking-[-0.02em]">关于</h1>
      <p class="mt-[3px] mb-0 text-xs leading-[18px] text-muted-foreground">应用与运行时信息</p>
    </div>
    <div class="mt-5 max-w-[430px] overflow-hidden rounded-lg border border-border bg-popover p-5 shadow-sm">
      <div class="flex justify-between gap-4 border-b border-border py-2.5 text-[11px]"><span>当前版本</span><strong>{{ version || '—' }}</strong></div>
      <div class="flex justify-between gap-4 border-b border-border py-2.5 text-[11px]"><span>执行核心</span><strong>Pi Agent</strong></div>
      <p class="mt-3 mb-0 text-[10px] leading-4 text-muted-foreground">当前构建不包含自动更新。发布升级由安装包和发行渠道管理。</p>
      <small class="mt-4 block text-[10px] text-muted-foreground">Copyright © micromatrix.org</small>
    </div>
  </section>
</template>
