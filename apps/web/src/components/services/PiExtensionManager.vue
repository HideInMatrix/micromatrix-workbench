<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import PiSkillEditor from './PiSkillEditor.vue'
import { desktopApi } from '../../api/desktop'
import type { PiExtensionConfigurationDto, PiExtensionsDto, PiMcpConnectionDto } from '../../types'

const emit = defineEmits<{ changed: [] }>()
const state = ref<PiExtensionsDto | null>(null)
const busy = ref(false)
const form = ref<'mcp' | 'skill' | ''>('')
const mcp = ref(newConnection())
const argsText = ref('[]')
const envText = ref('{}')
const headersText = ref('{}')
const skillId = ref('')
const skillPath = ref('')
const skillDescription = ref('')
const skillInstructions = ref('')
const skillMode = ref<'import' | 'create'>('import')
const editingId = ref('')
const credentials = ref<Record<string, string | null>>(Object.create(null))
const credentialKeys = computed(() => {
  try {
    const references = mcp.value.transport === 'stdio' ? Object.values(JSON.parse(envText.value)) : Object.values(JSON.parse(headersText.value)).flatMap(value => [...String(value).matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map(match => match[1]))
    return [...new Set(references)].filter((name): name is string => typeof name === 'string' && /^[A-Za-z_][A-Za-z0-9_]*$/.test(name))
  } catch { return [] }
})
const configuredKeys = computed(() => state.value?.mcp_status?.[mcp.value.id]?.keys ?? [])
function credentialUpdates() { return Object.fromEntries(Object.entries(credentials.value).filter(([, value]) => value === null || Boolean(value))) }
async function oauth(id: string) {
  await action(async () => {
    const result = await desktopApi.loginPiMcp(id)
    try { await desktopApi.openAuthorizationUrl(result.url) }
    catch (error) { await desktopApi.cancelPiMcpLogin(id); throw error }
    toast.success('请在浏览器完成授权；授权完成后点击 Runtime 启动。')
  })
}
let timer: ReturnType<typeof setInterval> | undefined
const fieldClass = 'mt-1 h-9 w-full rounded-lg border border-border bg-background px-3 text-xs outline-none focus:ring-2 focus:ring-ring/30 disabled:opacity-50'

function newConnection(): PiMcpConnectionDto {
  return { id: '', name: '', enabled: true, transport: 'stdio', command: '', args: [], url: '', envRefs: {}, headers: {}, auth: 'none' }
}
async function refresh() {
  const previous = state.value
  state.value = await desktopApi.piExtensions()
  if (previous && (previous.running !== state.value.running || JSON.stringify(previous.mcp_status) !== JSON.stringify(state.value.mcp_status))) emit('changed')
}
async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  try { await work(); await refresh(); emit('changed') }
  catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
  finally { busy.value = false }
}
async function save(configuration: PiExtensionConfigurationDto) {
  await desktopApi.configurePiExtensions(configuration)
  toast.success('Pi 扩展配置已保存；点击 Runtime 启动后加载。')
}
function editConnection(connection?: PiMcpConnectionDto) {
  mcp.value = connection ? { auth: 'none', ...connection, args: [...connection.args], envRefs: { ...connection.envRefs }, headers: { ...connection.headers } } : newConnection()
  if ((connection?.id ?? '') !== editingId.value) credentials.value = Object.create(null)
  editingId.value = connection?.id ?? ''
  argsText.value = JSON.stringify(mcp.value.args, null, 2)
  envText.value = JSON.stringify(mcp.value.envRefs, null, 2)
  headersText.value = JSON.stringify(mcp.value.headers, null, 2)
  form.value = 'mcp'
}
function connectionDraft(): PiMcpConnectionDto {
  const stdio = mcp.value.transport === 'stdio'
  return { ...mcp.value, args: stdio ? JSON.parse(argsText.value) : [], envRefs: stdio ? JSON.parse(envText.value) : {}, headers: stdio ? {} : JSON.parse(headersText.value) }
}
async function saveMcp() {
  await action(async () => {
    const configuration = state.value!.configuration
    const connection = connectionDraft()
    if (connection.id === 'computer_use') throw new Error('Computer Use 已内置，请使用上方开关，不要添加重复服务。')
    if (configuration.mcp.some(item => item.id === connection.id && item.id !== editingId.value)) throw new Error('MCP ID 已存在')
    await save({ ...configuration, mcp: [...configuration.mcp.filter(item => item.id !== editingId.value), connection] })
    const updates = credentialUpdates()
    if (Object.keys(updates).length) await desktopApi.setPiMcpCredentials(connection.id, updates)
    editingId.value = connection.id
    // Keep entered secrets in this editor after saving, never blank them.
  })
}
async function testMcp() {
  await action(async () => {
    const draft = connectionDraft()
    if (Object.keys(credentialUpdates()).length) {
      if (!editingId.value) throw new Error('填入本地密钥后请先保存，再测试连接。')
      await desktopApi.setPiMcpCredentials(editingId.value, credentialUpdates())
    }
    const result = await desktopApi.testPiMcp(draft)
    toast.success(`连接成功，发现 ${result.tools.length} 个工具；测试连接已关闭。`)
  })
}
async function saveSkill() {
  await action(async () => {
    if (skillMode.value === 'create') await desktopApi.createPiSkill(skillId.value, skillDescription.value, skillInstructions.value)
    else {
      const configuration = state.value!.configuration
      if (configuration.skills.some(item => item.id === skillId.value)) throw new Error('Skill 来源 ID 已存在')
      await save({ ...configuration, skills: [...configuration.skills, { id: skillId.value, path: skillPath.value, enabled: true }] })
    }
    toast.success('Skill 已添加，启动后由 Pi 加载。')
    form.value = ''
  })
}
async function chooseSkillPath() {
  await action(async () => { const selected = await desktopApi.chooseWorkspace(skillPath.value); if (selected) skillPath.value = selected })
}
async function changeEnabled(kind: 'mcp' | 'skills', id: string, enabled: boolean) {
  await action(async () => {
    const configuration = state.value!.configuration
    await save({ ...configuration, [kind]: configuration[kind].map(item => item.id === id ? { ...item, enabled } : item) })
  })
}
async function remove(kind: 'mcp' | 'skills', id: string) {
  await action(async () => {
    const configuration = state.value!.configuration
    await save({ ...configuration, [kind]: configuration[kind].filter(item => item.id !== id) })
  })
}
onMounted(() => {
  void refresh().catch(error => toast.error(error instanceof Error ? error.message : String(error)))
  timer = setInterval(() => { if (!busy.value) void refresh().catch(() => {}) }, 2500)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <section class="mt-6">
    <div class="flex items-center justify-between gap-3">
      <h2 class="m-0 text-sm font-medium">MCP 服务</h2>
      <div class="flex gap-2">
        <Button size="sm" variant="outline" :disabled="busy || !state || state.running" @click="editConnection()">添加 MCP</Button>
      </div>
    </div>
    <div v-if="form === 'mcp'" class="mt-3 rounded-xl border border-border bg-card p-4">
      <fieldset :disabled="busy || !state || state.running" class="space-y-3 disabled:opacity-60">
          <h3 class="m-0 text-sm font-medium">{{ editingId ? '编辑' : '添加' }} MCP 服务</h3>
          <div class="grid grid-cols-2 gap-3">
            <label class="text-xs">ID<input v-model="mcp.id" :class="fieldClass" placeholder="docs_mcp" :disabled="Boolean(editingId)" /></label>
            <label class="text-xs">名称<input v-model="mcp.name" :class="fieldClass" placeholder="文档服务" /></label>
          </div>
          <label class="block text-xs">传输<select v-model="mcp.transport" :class="fieldClass"><option value="stdio">stdio · 本地子进程</option><option value="http">Streamable HTTP</option></select></label>
          <template v-if="mcp.transport === 'stdio'">
            <label class="block text-xs">可执行程序<input v-model="mcp.command" :class="fieldClass" placeholder="npx 或绝对路径（不是 shell 命令）" /></label>
            <label class="block text-xs">参数 JSON 数组<textarea v-model="argsText" :class="[fieldClass, 'h-20 py-2 font-mono']" placeholder='["-y", "your-mcp-package"]' /></label>
            <label class="block text-xs">环境变量引用 JSON<textarea v-model="envText" :class="[fieldClass, 'h-20 py-2 font-mono']" placeholder='{"API_KEY":"MY_API_KEY"}' /></label>
          </template>
          <template v-else>
            <label class="block text-xs">MCP 地址<input v-model="mcp.url" :class="fieldClass" placeholder="https://example.com/mcp" /></label>
            <label class="block text-xs">认证<select v-model="mcp.auth" :class="fieldClass"><option value="none">无 / Header 密钥</option><option value="oauth">OAuth · CIMD 浏览器授权</option></select></label>
            <template v-if="mcp.auth === 'oauth'">
              <label class="block text-xs">自己的 CIMD 文档 URL<input v-model="mcp.clientMetadataUrl" :class="fieldClass" placeholder="https://your-domain.example/oauth/client.json" /></label>
              <label class="block text-xs">文档中登记的本机回调<input v-model="mcp.oauthRedirectUri" :class="fieldClass" placeholder="http://127.0.0.1:18456/oauth/callback" /></label>
              <details class="text-xs leading-5 text-muted-foreground">
                <summary class="cursor-pointer">CIMD 配置要求</summary>
                <p class="mt-2">自行托管公开 HTTPS JSON，client_id 等于文档 URL，redirect_uris 包含准确的本机回调，且端口空闲。不能使用其他应用的元数据；不支持 DCR-only 服务。</p>
              </details>
            </template>
            <label class="block text-xs">Header 引用 JSON<textarea v-model="headersText" :class="[fieldClass, 'h-20 py-2 font-mono']" placeholder='{"Authorization":"Bearer ${MY_TOKEN}"}' /></label>
          </template>
          <div v-if="credentialKeys.length" class="space-y-2 rounded-lg border border-border p-3">
            <p class="text-xs leading-5 text-muted-foreground">留空保留，清除删除。启用本机保存后写入本地文件，非系统钥匙串。</p>
            <div v-for="key in credentialKeys" :key="key" class="flex items-end gap-2">
              <label class="flex-1 text-xs">{{ key }} {{ configuredKeys.includes(key) ? '· 已配置' : '' }}<input :value="credentials[key] ?? ''" type="password" autocomplete="off" :class="fieldClass" placeholder="留空保留 / 使用服务环境变量" @input="credentials[key] = ($event.target as HTMLInputElement).value" /></label>
              <Button size="sm" variant="outline" @click="credentials[key] = null">清除</Button>
            </div>
          </div>
          <div class="flex justify-end gap-2"><Button size="sm" variant="outline" @click="form = ''">取消</Button><Button size="sm" variant="outline" @click="testMcp">测试连接</Button><Button size="sm" @click="saveMcp">保存</Button></div>
      </fieldset>
    </div>
    <div v-if="state" class="mt-3 divide-y divide-border rounded-xl border border-border bg-card">
      <div v-for="connection in state.configuration.mcp" :key="`mcp:${connection.id}`" class="flex flex-wrap items-center gap-2 px-4 py-3">
        <div class="min-w-0 basis-40 flex-1"><div class="text-sm font-medium">{{ connection.name }}</div><div class="mt-1 truncate text-xs text-muted-foreground">MCP · {{ connection.id }} · {{ connection.transport }} · {{ connection.url || connection.command }}</div></div>
        <div class="text-xs text-muted-foreground">{{ state.mcp_status?.[connection.id]?.status ?? 'stopped' }}<span v-if="connection.auth === 'oauth'"> · OAuth {{ state.mcp_status?.[connection.id]?.oauth ?? 'logged_out' }}</span><div>{{ state.mcp_status?.[connection.id]?.message }}</div></div>
        <Button v-if="state.running && connection.enabled" size="sm" variant="ghost" :disabled="busy" @click="action(async () => { await desktopApi.refreshPiMcp(connection.id); toast.success('工具目录已刷新') })">刷新工具</Button>
        <template v-if="connection.auth === 'oauth'">
          <Button size="sm" variant="ghost" :disabled="busy || state.running" @click="oauth(connection.id)">授权登录</Button>
          <Button size="sm" variant="ghost" :disabled="busy || state.running" @click="action(async () => { await desktopApi.logoutPiMcp(connection.id) })">注销</Button>
          <Button v-if="state.mcp_status?.[connection.id]?.oauth === 'pending'" size="sm" variant="ghost" :disabled="busy" @click="action(async () => { await desktopApi.cancelPiMcpLogin(connection.id) })">取消授权</Button>
        </template>
        <Button size="sm" variant="ghost" :disabled="busy || state.running" @click="editConnection(connection)">编辑</Button>
        <Button size="sm" variant="ghost" :disabled="busy || state.running" @click="remove('mcp', connection.id)">移除</Button>
        <Switch :model-value="connection.enabled" :disabled="busy || state.running" :aria-label="`启停 MCP ${connection.name}`" @update:model-value="value => changeEnabled('mcp', connection.id, value)" />
      </div>
      <div v-if="!state.configuration.mcp.length" class="px-4 py-5 text-center text-xs text-muted-foreground">暂无外部 MCP 服务</div>
    </div>
    <div class="mt-6 flex items-center justify-between gap-3">
      <h2 class="m-0 text-sm font-medium">Skills</h2>
      <Button size="sm" variant="outline" :disabled="busy || !state || state.running" @click="form = 'skill'">添加 Skill</Button>
    </div>
    <div v-if="form === 'skill'" class="mt-3 rounded-xl border border-border bg-card p-4">
      <fieldset :disabled="busy || !state || state.running" class="space-y-3 disabled:opacity-60">
          <h3 class="m-0 text-sm font-medium">添加标准 Pi Skill</h3>
          <label class="block text-xs">来源 ID<input v-model="skillId" :class="fieldClass" placeholder="review" /></label>
          <label class="block text-xs">方式<select v-model="skillMode" :class="fieldClass"><option value="import">导入本地 Skill 目录 / SKILL.md</option><option value="create">创建 SKILL.md</option></select></label>
          <div v-if="skillMode === 'import'">
            <label class="block text-xs">绝对路径<div class="flex items-end gap-2"><input v-model="skillPath" :class="fieldClass" placeholder="/path/to/skills" /><Button size="sm" variant="outline" @click="chooseSkillPath">选择目录</Button></div></label>
            <p class="mt-2 text-xs text-muted-foreground">仅引用原目录，不复制或删除文件。</p>
          </div>
          <template v-else>
            <label class="block text-xs">描述<input v-model="skillDescription" :class="fieldClass" /></label>
            <label class="block text-xs">方法说明<textarea v-model="skillInstructions" :class="[fieldClass, 'h-40 py-2']" /></label>
          </template>
          <div class="flex justify-end gap-2"><Button size="sm" variant="outline" @click="form = ''">取消</Button><Button size="sm" @click="saveSkill">添加</Button></div>
      </fieldset>
    </div>
    <div v-if="state" class="mt-3 divide-y divide-border rounded-xl border border-border bg-card">
      <div v-for="source in state.configuration.skills" :key="`skill:${source.id}`" class="flex flex-wrap items-center gap-2 px-4 py-3">
        <div class="min-w-0 basis-40 flex-1"><div class="text-sm font-medium">{{ source.id }}</div><div class="mt-1 truncate text-xs text-muted-foreground">Skill 来源 · {{ source.path }}</div></div>
        <Button size="sm" variant="ghost" :disabled="busy || state.running" @click="remove('skills', source.id)">移除引用</Button>
        <Switch :model-value="source.enabled" :disabled="busy || state.running" :aria-label="`启停 Skill 来源 ${source.id}`" @update:model-value="value => changeEnabled('skills', source.id, value)" />
      </div>
      <div v-if="!state.configuration.skills.length" class="px-4 py-5 text-center text-xs text-muted-foreground">暂无 Skills</div>
    </div>
    <PiSkillEditor v-if="state && state.configuration.skills.length" :key="JSON.stringify(state.configuration.skills)" :running="state.running" @changed="emit('changed')" />
  </section>
</template>
