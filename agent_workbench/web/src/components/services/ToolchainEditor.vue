<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ChevronDown, Info, Plus, RefreshCw, Terminal, Trash2, X } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form'
import { desktopApi } from '../../api/desktop'
import type { ToolchainProposal, ToolchainRegistration } from '../../types'

const registrations = defineModel<ToolchainRegistration[]>({ default: () => [] })
const props = defineProps<{ locked: boolean; mode: string }>()
const program = ref('node')
const executable = ref('')
const extraRoots = ref('')
const proposal = ref<ToolchainProposal | null>(null)
const busy = ref(false)
const error = ref('')
const editing = ref(false)
const expanded = ref<string | null>(null)
const pathInput = ref<HTMLInputElement | null>(null)
const notice = ref('')
watch([program, executable, extraRoots], () => { proposal.value = null })

async function openEditor(item?: ToolchainRegistration) {
  editing.value = true
  error.value = ''
  program.value = item?.program || 'node'
  executable.value = item?.executable || ''
  extraRoots.value = item?.read_roots.join('\n') || ''
  proposal.value = null
  await nextTick()
  pathInput.value?.focus()
  if (item) await inspect()
}

function closeEditor() {
  editing.value = false
  proposal.value = null
  error.value = ''
}

async function inspect() {
  if (props.locked || busy.value) return
  busy.value = true
  error.value = ''
  proposal.value = null
  try {
    proposal.value = await desktopApi.inspectToolchain(program.value, executable.value,
      extraRoots.value.split('\n').map(item => item.trim()).filter(Boolean))
  } catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}

async function register() {
  const selected = proposal.value
  if (!selected || props.locked || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await desktopApi.registerToolchain(selected.program, selected.executable, selected.read_roots)
    registrations.value = [...registrations.value.filter(item => item.program !== result.program), result]
    closeEditor()
    notice.value = '已更新，保存 Work 后生效。'
  } catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}

function remove(item: ToolchainRegistration) {
  if (props.locked || busy.value) return
  registrations.value = registrations.value.filter(value => value.program !== item.program)
  if (expanded.value === item.program) expanded.value = null
  notice.value = '已移除，保存 Work 后生效。'
}
</script>

<template>
  <section class="grid min-w-0 gap-3 text-xs font-normal" aria-label="工具链">
    <header class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <h3 class="m-0 text-xs font-medium text-foreground">工具链</h3>
        <span v-if="registrations.length" class="text-[10px] tabular-nums text-muted-foreground">{{ registrations.length }}</span>
      </div>
      <Button v-if="!editing" type="button" size="sm" variant="ghost" class="h-7 gap-1.5 px-2 text-[11px]" :disabled="locked || busy" @click="openEditor()">
        <Plus :size="13" />手动添加
      </Button>
    </header>

    <p v-if="mode === 'dangerous'" class="m-0 text-[11px] text-destructive">危险模式：工具执行不受沙箱隔离。</p>
    <p v-if="locked" class="m-0 text-[11px] text-muted-foreground">停止 Work 后可手动修改工具。</p>

    <div v-if="registrations.length" class="overflow-hidden rounded-lg border border-border bg-background">
      <article v-for="item in registrations" :key="item.program" class="border-b border-border last:border-b-0">
        <div class="flex items-center gap-2 px-3 py-3">
          <button type="button" class="toolchain-entry group flex min-w-0 flex-1 items-center gap-3 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring" :aria-label="`${item.program} 路径详情`" :aria-expanded="expanded === item.program" @click="expanded = expanded === item.program ? null : item.program">
            <span class="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary text-muted-foreground"><Terminal :size="16" /></span>
            <span class="grid min-w-0 gap-1">
              <span class="flex items-center gap-2">
                <span class="font-medium text-foreground">{{ item.program }}</span>
                <span v-if="item.version" class="font-mono text-[10px] text-muted-foreground">{{ item.version }}</span>
                <ChevronDown :size="12" class="shrink-0 text-muted-foreground transition-transform" :class="{ 'rotate-180': expanded === item.program }" />
              </span>
              <span class="truncate font-mono text-[10px] leading-4 text-muted-foreground" :title="item.executable">{{ item.executable }}</span>
            </span>
          </button>
          <div class="flex shrink-0 items-center gap-0.5">
            <Button type="button" size="icon" variant="ghost" class="size-7 text-muted-foreground" :disabled="locked || busy" :aria-label="`重新确认 ${item.program}`" title="重新确认" @click="openEditor(item)"><RefreshCw :size="13" /></Button>
            <Button type="button" size="icon" variant="ghost" class="size-7 text-muted-foreground hover:text-destructive" :disabled="locked || busy" :aria-label="`移除 ${item.program}`" title="移除" @click="remove(item)"><Trash2 :size="13" /></Button>
          </div>
        </div>
        <div v-if="expanded === item.program" class="grid gap-3 border-t border-border bg-secondary/40 px-3 py-3 text-[11px]">
          <div class="grid gap-1"><span class="text-muted-foreground">程序路径</span><code class="select-text break-all text-foreground">{{ item.executable }}</code></div>
          <div class="grid gap-1"><span class="text-muted-foreground">只读目录</span><code v-for="root in item.read_roots" :key="root" class="select-text break-all text-foreground">{{ root }}</code></div>
        </div>
      </article>
    </div>
    <div v-else-if="!editing" class="flex items-center gap-3 rounded-lg border border-dashed border-border px-3 py-4">
      <Terminal :size="17" class="shrink-0 text-muted-foreground" />
      <div class="grid gap-1"><span class="text-[11px] text-foreground">尚未添加工具</span><span class="text-[11px] text-muted-foreground">首次使用时自动检测，授权后记住。</span></div>
    </div>

    <div v-if="editing" class="grid gap-3 rounded-lg border border-border bg-secondary/30 p-3">
      <div class="flex items-center justify-between"><span class="text-[11px] font-medium">手动配置</span><Button type="button" size="icon" variant="ghost" class="size-6" :disabled="busy" aria-label="关闭手动配置" @click="closeEditor"><X :size="13" /></Button></div>
      <div class="grid grid-cols-[140px_minmax(0,1fr)] gap-2 max-[420px]:grid-cols-1">
        <FormField label="工具"><input v-model.trim="program" :disabled="locked || busy" placeholder="例如 git、node、ffmpeg" /></FormField>
        <FormField label="程序路径"><input ref="pathInput" v-model.trim="executable" :disabled="locked || busy" placeholder="程序的绝对路径" /></FormField>
      </div>
      <details class="text-[11px] text-muted-foreground">
        <summary class="w-fit cursor-pointer rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">额外只读目录（可选）</summary>
        <FormField class="mt-2"><textarea v-model="extraRoots" rows="2" :disabled="locked || busy" aria-label="额外只读目录" placeholder="每行一个；留空自动识别" /></FormField>
      </details>
      <div v-if="!proposal" class="flex justify-end"><Button type="button" size="sm" variant="outline" class="h-8 px-3 text-xs" :disabled="locked || busy || !executable" @click="inspect">{{ busy ? '检查中…' : '检查路径' }}</Button></div>
      <div v-else class="grid gap-2 border-t border-border pt-3">
        <span class="text-[11px] text-muted-foreground">确认只读访问范围</span>
        <code v-for="root in proposal.read_roots" :key="root" class="break-all text-[11px] text-foreground">{{ root }}</code>
        <div class="flex justify-end"><Button type="button" size="sm" class="h-8 px-3 text-xs" :disabled="locked || busy" @click="register">{{ busy ? '注册中…' : '确认并注册' }}</Button></div>
      </div>
      <p v-if="error" role="alert" class="m-0 break-words text-[11px] text-destructive">{{ error }}</p>
    </div>

    <p v-if="notice" role="status" class="m-0 text-[11px] text-muted-foreground">{{ notice }}</p>
    <details class="text-[11px] leading-5 text-muted-foreground">
      <summary class="flex w-fit cursor-pointer list-none items-center gap-1.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"><Info :size="12" />使用说明</summary>
      <p class="mt-1.5 mb-0">首次使用时由 Workbench Host 在真实用户环境中通过命令解析工具路径，只把绝对路径和必要只读范围交给授权界面；确认后保存到当前 Profile。</p>
      <p class="mt-1 mb-0">注册阶段不执行工具，只冻结程序路径、只读范围和文件指纹；真正命令仍在安全与受信任模式的正常沙箱中执行。</p>
    </details>
  </section>
</template>

<style scoped>
/* The app's global button rule centers content; list entries must stay left-aligned. */
.toolchain-entry { justify-content: flex-start; gap: 12px; }
</style>
