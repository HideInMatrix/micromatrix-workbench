<script setup lang="ts">
import { Check, Copy, Eye, EyeOff, LoaderCircle, Plus, Trash2 } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { CheckField, FormField, FormGrid } from '@/components/ui/form'
import { InputGroup, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import type { GatewayDiagnosticDto, GatewayDraft, GatewayMemberDraft } from '../../types'
import { normalizePath } from './serviceModels'
import ServiceDiagnosticPanel from './ServiceDiagnosticPanel.vue'

const draft = defineModel<GatewayDraft>('draft', { required: true })
const tunnelTokenVisible = defineModel<boolean>('tunnelTokenVisible', { required: true })

defineProps<{
  isNew: boolean
  locked: boolean
  busy: boolean
  selectedRunning: boolean
  selectedIsStarting: boolean
  copiedUrl: string
  diagnostic: GatewayDiagnosticDto | null
  showDiagnostic: boolean
  isRootProfile: (member: GatewayMemberDraft, index: number) => boolean
  profileEnabled: (member: GatewayMemberDraft, index: number) => boolean
  runtimeUrl: (member: GatewayMemberDraft) => string
  isOAuthPasswordVisible: (member: GatewayMemberDraft) => boolean
}>()

const emit = defineEmits<{
  setMode: [mode: 'single' | 'multi']
  addProfile: []
  removeProfile: [index: number]
  chooseWorkspace: [member: GatewayMemberDraft]
  toggleOAuthPassword: [member: GatewayMemberDraft]
  copyUrl: [value: string]
  test: []
  delete: []
  save: []
  toggle: []
}>()

function profilePublicUrl(member: GatewayMemberDraft, index: number): string {
  return index === 0 ? draft.value.network.public_url : member.public_url
}

function updateProfilePublicUrl(member: GatewayMemberDraft, index: number, event: Event) {
  const value = (event.target as HTMLInputElement).value
  member.public_url = value
  if (index === 0) draft.value.network.public_url = value
}
</script>

<template>
  <section class="overflow-hidden rounded-lg border border-border bg-popover p-4 shadow-sm">
    <div class="mb-4 flex items-center justify-between gap-3.5">
      <div>
        <h2 class="m-0 text-[13px] leading-5 font-medium">{{ isNew ? '新建服务' : '服务设置' }}</h2>
        <p class="mt-px mb-0 text-[11px] leading-4 text-muted-foreground">运行模式由你明确选择；子 Profile 配置可以保留，但单 Workspace 模式不会启动它们。</p>
      </div>
      <span
        :class="[
          'inline-flex min-h-[22px] items-center whitespace-nowrap rounded-full px-2 text-[10px] font-medium',
          selectedIsStarting
            ? 'gap-[5px] bg-stone-500/10 text-stone-600'
            : selectedRunning
              ? 'bg-success/10 text-success'
              : 'bg-secondary text-muted-foreground',
        ]"
      >
        <LoaderCircle v-if="selectedIsStarting" class="animate-spin" :size="12" />
        {{ selectedIsStarting ? '启动中…' : selectedRunning ? '运行中' : '已停止' }}
      </span>
    </div>

    <div class="mt-3.5 inline-flex w-fit items-center gap-0.5 rounded-lg border border-border bg-secondary p-[3px]" role="tablist" aria-label="Workspace 运行模式">
      <button
        v-for="mode in (['single', 'multi'] as const)"
        :key="mode"
        type="button"
        role="tab"
        :class="[
          'min-h-[30px] cursor-pointer rounded-md border-0 bg-transparent px-3.5 text-[11px] font-medium text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60',
          { 'bg-yellow-400 text-black shadow-sm': draft.mode === mode },
        ]"
        :aria-selected="draft.mode === mode"
        :disabled="locked"
        @click="emit('setMode', mode)"
      >
        {{ mode === 'single' ? '单 Workspace' : '多 Workspace' }}
      </button>
    </div>
    <p class="mt-[7px] mb-0 text-[11px] leading-[18px] text-muted-foreground">
      {{ draft.mode === 'single'
        ? '当前只启动主 Workspace；已配置的子 Profile 会保留，但不会参与本次运行。'
        : '当前启动全部 Profile；每个 Profile 使用独立 Public Hostname，但共同回源到同一个本地端口。' }}
    </p>

    <FormGrid>
      <FormField label="服务名称" span="2"><input v-model.trim="draft.name" :disabled="locked" placeholder="例如：公司开发环境" /></FormField>
      <FormField label="本地端口"><input v-model.number="draft.port" :disabled="locked" type="number" min="1" max="65535" /></FormField>
      <FormField label="监听地址"><input v-model.trim="draft.host" disabled /></FormField>
      <FormField label="网络方案" span="2">
        <select v-model="draft.network.provider" :disabled="locked">
          <option value="cloudflare">Cloudflare Tunnel</option><option value="frp">FRP</option><option value="ngrok">ngrok</option>
          <option value="tailscale">Tailscale Funnel</option><option value="external">自定义公网 URL</option>
        </select>
      </FormField>
      <FormField v-if="draft.network.provider === 'cloudflare'" label="Tunnel Token" span="2">
        <InputGroup>
          <InputGroupInput v-model="draft.network.options.tunnel_token" :disabled="locked" :type="tunnelTokenVisible ? 'text' : 'password'" autocomplete="off" />
          <InputGroupButton
            :aria-label="tunnelTokenVisible ? '隐藏 Tunnel Token' : '显示 Tunnel Token'"
            :aria-pressed="tunnelTokenVisible"
            :title="tunnelTokenVisible ? '隐藏 Tunnel Token' : '显示 Tunnel Token'"
            @click="tunnelTokenVisible = !tunnelTokenVisible"
          ><EyeOff v-if="tunnelTokenVisible" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
        </InputGroup>
      </FormField>
      <template v-else-if="draft.network.provider === 'frp'">
        <FormField label="frpc 路径" span="2"><input v-model.trim="draft.network.options.executable" :disabled="locked" /></FormField>
        <FormField label="frpc 配置文件" span="2"><input v-model.trim="draft.network.options.config_file" :disabled="locked" /></FormField>
      </template>
      <template v-else-if="draft.network.provider === 'ngrok'">
        <FormField label="ngrok 路径"><input v-model.trim="draft.network.options.executable" :disabled="locked" /></FormField>
        <FormField label="Auth Token"><input v-model="draft.network.options.authtoken" :disabled="locked" type="password" /></FormField>
      </template>
      <FormField v-else-if="draft.network.provider === 'tailscale'" label="Tailscale 路径" span="2"><input v-model.trim="draft.network.options.executable" :disabled="locked" /></FormField>
      <CheckField span="2"><input v-model="draft.remember_secrets" type="checkbox" /><span>在本机持久化网络 Token 与 OAuth Password</span></CheckField>
    </FormGrid>

    <div class="mt-[22px] mb-2.5 flex items-center justify-between gap-4">
      <Button variant="outline" size="sm" class="min-h-[30px] px-2.5" :disabled="locked" @click="emit('addProfile')"><Plus :size="14" /> 添加 Profile</Button>
    </div>

    <div class="grid gap-3">
      <article
        v-for="(member, index) in draft.members"
        :key="member.server_id || `new-${index}`"
        :class="['overflow-hidden rounded-[9px] border border-border bg-card', { 'opacity-60': !profileEnabled(member, index) }]"
      >
        <header class="flex items-center justify-between border-b border-border px-3 py-2.5">
          <div class="flex items-center gap-2">
            <strong>{{ isRootProfile(member, index) ? '主 Workspace' : `Profile ${index + 1}` }}</strong>
            <span v-if="!profileEnabled(member, index)" class="rounded-full border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">未启用</span>
          </div>
          <Button variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground" :disabled="locked || draft.members.length <= 1 || isRootProfile(member, index)" @click="emit('removeProfile', index)"><Trash2 :size="14" /></Button>
        </header>

        <FormGrid class="p-3">
          <FormField label="名称"><input v-model.trim="member.name" :disabled="locked" /></FormField>
          <FormField label="本地路由"><input :value="isRootProfile(member, index) ? '/' : normalizePath(member.instance_path)" disabled /></FormField>
          <FormField label="Public Hostname" span="2">
            <input
              :value="profilePublicUrl(member, index)"
              :disabled="locked || draft.network.provider === 'tailscale'"
              placeholder="例如 https://mcp-claude.example.com"
              @input="updateProfilePublicUrl(member, index, $event)"
            />
          </FormField>
          <FormField label="Workspace" span="2">
            <InputGroup>
              <InputGroupInput v-model="member.workspace" :disabled="locked" />
              <InputGroupButton :disabled="locked" @click="emit('chooseWorkspace', member)">选择</InputGroupButton>
            </InputGroup>
          </FormField>
          <FormField label="OAuth Password">
            <InputGroup>
              <InputGroupInput v-model="member.oauth_password" :disabled="locked" :type="isOAuthPasswordVisible(member) ? 'text' : 'password'" autocomplete="off" />
              <InputGroupButton
                :aria-label="isOAuthPasswordVisible(member) ? '隐藏 OAuth Password' : '显示 OAuth Password'"
                :aria-pressed="isOAuthPasswordVisible(member)"
                :title="isOAuthPasswordVisible(member) ? '隐藏 OAuth Password' : '显示 OAuth Password'"
                @click="emit('toggleOAuthPassword', member)"
              ><EyeOff v-if="isOAuthPasswordVisible(member)" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
            </InputGroup>
          </FormField>
          <FormField label="权限模式"><select v-model="member.permission_mode" :disabled="locked"><option value="safe">Safe</option><option value="trusted">Trusted</option><option value="dangerous">Dangerous</option></select></FormField>
          <CheckField><input v-model="member.allow_network" :disabled="locked" type="checkbox" /><span>允许网络</span></CheckField>
          <CheckField><input v-model="member.enable_view_image" :disabled="locked" type="checkbox" /><span>启用图片工具</span></CheckField>
        </FormGrid>

        <div v-if="runtimeUrl(member)" class="flex items-center gap-2 border-t border-border bg-secondary/50 px-3 py-[9px]">
          <code class="min-w-0 flex-1 truncate text-[11px] font-medium text-blue-600 dark:text-blue-400">{{ runtimeUrl(member) }}</code>
          <Button variant="outline" size="icon" class="h-7 w-7 text-muted-foreground" @click="emit('copyUrl', runtimeUrl(member))"><Check v-if="copiedUrl === runtimeUrl(member)" :size="13" /><Copy v-else :size="13" /></Button>
        </div>
      </article>
    </div>

    <ServiceDiagnosticPanel v-if="showDiagnostic" :diagnostic="diagnostic" :busy="busy" @test="emit('test')" />

    <div class="mt-4 flex justify-between gap-2 border-t border-border pt-3.5">
      <Button v-if="!isNew" variant="destructiveOutline" size="sm" :disabled="busy || locked" @click="emit('delete')">删除</Button>
      <div class="ml-auto flex gap-2">
        <Button variant="outline" size="sm" :disabled="busy || locked" @click="emit('save')">{{ isNew ? '创建服务' : '保存' }}</Button>
        <Button v-if="!isNew && !selectedRunning" size="sm" :disabled="busy || selectedIsStarting" @click="emit('toggle')">启动</Button>
        <Button v-else-if="!isNew" variant="destructiveOutline" size="sm" :disabled="busy" @click="emit('toggle')">停止</Button>
      </div>
    </div>
  </section>
</template>
