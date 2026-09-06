<script setup lang="ts">
import { ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
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
watch([program, executable, extraRoots], () => { proposal.value = null })

async function inspect() {
  busy.value = true
  error.value = ''
  proposal.value = null
  try {
    proposal.value = await desktopApi.inspectToolchain(program.value, executable.value,
      extraRoots.value.split('\n').map(item => item.trim()).filter(Boolean))
  } catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}

async function revalidate(item: ToolchainRegistration) {
  program.value = item.program
  executable.value = item.executable
  extraRoots.value = item.read_roots.join('\n')
  await inspect()
}

async function register() {
  const selected = proposal.value
  if (!selected || props.locked) return
  busy.value = true
  error.value = ''
  try {
    const result = await desktopApi.registerToolchain(selected.program, selected.executable, selected.read_roots)
    registrations.value = [...registrations.value.filter(item => item.program !== result.program), result]
    proposal.value = null
  } catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}
</script>

<template>
  <div class="grid gap-2 text-xs">
    <p class="m-0 text-muted-foreground">
      {{ mode === 'dangerous'
        ? '危险模式不提供任务执行隔离；仅注册验证在沙箱内进行。'
        : '安全 / 受信任模式必须通过 OS 文件与网络隔离自检，失败时拒绝启动。工具链只读，缓存独立；子进程受同一沙箱约束。' }}
      AI 首次使用缺失工具时会自动检测并请求授权，确认后记住当前 Profile。下方手填路径仅用于检测失败或更换工具。注册验证不会开放整个 Home。
    </p>
    <div v-for="item in registrations" :key="item.program" class="rounded border border-border p-2">
      <div class="flex items-center justify-between gap-2">
        <strong>{{ item.program }} · {{ item.version }}</strong>
        <Button size="sm" variant="outline" :disabled="locked || busy" @click="revalidate(item)">重新验证</Button>
        <Button size="sm" variant="outline" :disabled="locked || busy" @click="registrations = registrations.filter(value => value.program !== item.program)">移除</Button>
      </div>
      <div class="break-all">{{ item.executable }}</div>
      <div v-for="root in item.read_roots" :key="root" class="break-all text-muted-foreground">只读：{{ root }}</div>
    </div>
    <select v-model="program" :disabled="locked || busy" aria-label="注册程序">
      <option v-for="name in ['node', 'python', 'python3', 'npm', 'pnpm', 'npx', 'pip', 'pip3', 'yarn']" :key="name" :value="name">{{ name }}</option>
    </select>
    <input v-model.trim="executable" :disabled="locked || busy" aria-label="工具链程序路径" placeholder="程序绝对路径，例如 /Users/你/.nvmd/bin/node" />
    <textarea v-model="extraRoots" :disabled="locked || busy" aria-label="额外只读依赖目录" placeholder="必要的额外只读依赖目录，每行一个；留空自动推导安装目录" />
    <Button variant="outline" :disabled="locked || busy || !executable" @click="inspect">检查路径（不执行）</Button>
    <div v-if="proposal" class="rounded border border-border p-2">
      <p class="m-0">确认后将仅在沙箱中运行版本检测，并把以下目录授予该 Profile 只读权限：</p>
      <div v-for="root in proposal.read_roots" :key="root" class="break-all">{{ root }}</div>
      <Button class="mt-2" :disabled="locked || busy" @click="register">{{ busy ? '验证中…' : '确认权限并验证注册' }}</Button>
    </div>
    <p v-if="error" role="alert" class="m-0 text-destructive">{{ error }}</p>
    <p class="m-0 text-muted-foreground">注册后保存服务配置。路径、文件或版本改变会阻止执行；重新检查并注册即可，不需要危险模式。</p>
  </div>
</template>
