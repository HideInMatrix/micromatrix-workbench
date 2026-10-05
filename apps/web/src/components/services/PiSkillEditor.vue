<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { desktopApi } from '../../api/desktop'
const props = defineProps<{ running: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const skills = ref<Array<{ id: string; description: string }>>([])
const editor = ref<Awaited<ReturnType<typeof desktopApi.readPiSkill>> | null>(null)
const busy = ref(false)
async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  try { await work() } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
  finally { busy.value = false }
}
async function refresh() { await action(async () => { skills.value = await desktopApi.piSkillDocuments() }) }
async function edit(id: string) { await action(async () => { editor.value = await desktopApi.readPiSkill(id) }) }
async function save() {
  await action(async () => {
    if (!editor.value || props.running) return
    await desktopApi.editPiSkill(editor.value.id, editor.value.document, editor.value.revision)
    editor.value = await desktopApi.readPiSkill(editor.value.id)
    toast.success('Skill 已保存；下次启动 Runtime 加载新内容。'); emit('changed')
  })
}
onMounted(() => { void refresh() })
</script>
<template>
  <section class="mt-4 rounded-xl border border-border bg-card p-4">
    <div class="flex items-center justify-between"><h3 class="m-0 text-xs font-medium">Skill 文档与支持文件</h3><Button size="sm" variant="ghost" :disabled="busy" @click="refresh">刷新文档</Button></div>
    <p class="mt-2 text-[10px] text-muted-foreground">修改会写回导入的原文件；保留 frontmatter 和 name。移除来源只删除引用，不删除文件。支持文件由网页 AI 使用 skills_files / skills_file_read 安全读取，脚本不会自动执行。</p>
    <div v-for="skill in skills" :key="skill.id" class="mt-2 flex items-center justify-between gap-3"><span class="text-xs">{{ skill.id }} · {{ skill.description }}</span><Button size="sm" variant="outline" :disabled="busy" @click="edit(skill.id)">打开文档</Button></div>
    <div v-if="editor" class="mt-3 space-y-3">
      <h4 class="text-xs">{{ editor.id }} / SKILL.md</h4>
      <textarea v-model="editor.document" :disabled="running || busy" class="h-72 w-full rounded-lg border border-border bg-background p-3 font-mono text-xs" aria-label="完整 Skill 文档" />
      <div class="text-[10px] text-muted-foreground">支持文件（相对于 Skill 目录）：<div v-for="file in editor.files" :key="file.path">{{ file.path }} · {{ file.size }} bytes</div><span v-if="!editor.files.length">无</span></div>
      <div class="flex justify-end gap-2"><Button size="sm" variant="outline" :disabled="busy" @click="editor = null">关闭文档</Button><Button size="sm" :disabled="busy || running" @click="save">保存文档</Button></div>
    </div>
  </section>
</template>
