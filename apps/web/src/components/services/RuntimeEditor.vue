<script setup lang="ts">
import { computed } from 'vue'
import { Check, Copy, Eye, EyeOff, FolderOpen, Play, Square } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { CheckField, FormField, FormGrid } from '@/components/ui/form'
import { InputGroup, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import type { NetworkProviderDto, RuntimeDraft } from '../../types'
import PermissionModeField from './PermissionModeField.vue'
import BodyPluginEditor from './BodyPluginEditor.vue'

const draft = defineModel<RuntimeDraft>('draft', { required: true })
const tunnelTokenVisible = defineModel<boolean>('tunnelTokenVisible', { required: true })

const props = defineProps<{
  locked: boolean
  busy: boolean
  lifecycleBusy: boolean
  selectedRunning: boolean
  copiedUrl: string
  runtimeUrl: string
  networkProviders: NetworkProviderDto[]
  oauthPasswordVisible: boolean
}>()

const selectedProvider = computed(() => (
  props.networkProviders.find(item => item.key === draft.value.network.provider)
))

const emit = defineEmits<{
  chooseWorkspace: []
  toggleOAuthPassword: []
  copyUrl: [value: string]
  save: []
  toggleRunning: []
}>()
</script>

<template>
  <section class="overflow-hidden rounded-lg border border-border bg-popover p-4 shadow-sm">
    <div class="mb-4 flex items-center justify-between gap-3.5">
      <div>
        <h2 class="m-0 text-[13px] leading-5 font-medium">Runtime 设置</h2>
        <p class="mt-px mb-0 text-[11px] leading-4 text-muted-foreground">
          配置 Pi Runtime、OAuth、审批策略、插件与公网隧道；当前 Runtime 由启动/停止按钮控制。
        </p>
      </div>
      <span
        :class="[
          'inline-flex min-h-[22px] items-center whitespace-nowrap rounded-full px-2 text-[10px] font-medium',
          selectedRunning
            ? 'bg-success/10 text-success'
            : draft.enabled
              ? 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400'
              : 'bg-secondary text-muted-foreground',
        ]"
      >
        {{ selectedRunning ? '运行中' : draft.enabled ? '已停止 · 随应用启动' : '已停止' }}
      </span>
    </div>

    <FormGrid>
      <FormField label="Runtime 名称" span="2">
        <input v-model.trim="draft.name" :disabled="locked" placeholder="例如：Pi MCP Runtime" />
      </FormField>
      <FormField label="本地端口">
        <input v-model.number="draft.port" :disabled="locked" type="number" min="1" max="65535" />
      </FormField>
      <FormField label="监听地址"><input v-model.trim="draft.host" disabled /></FormField>

      <FormField label="公网域名" span="2">
        <input
          v-model.trim="draft.network.public_url"
          :disabled="locked || selectedProvider?.supports_public_url === false"
          placeholder="例如 https://mcp.example.com"
        />
      </FormField>

      <FormField label="工作目录" span="2">
        <InputGroup>
          <InputGroupInput v-model="draft.workspace" :disabled="locked" />
          <InputGroupButton
            :disabled="locked"
            aria-label="选择 Runtime 工作目录"
            title="选择 Runtime 工作目录"
            @click="emit('chooseWorkspace')"
          ><FolderOpen :size="15" /></InputGroupButton>
        </InputGroup>
      </FormField>

      <FormField label="网络方案" span="2">
        <select v-model="draft.network.provider" :disabled="locked">
          <option v-for="provider in networkProviders" :key="provider.key" :value="provider.key">
            {{ provider.label }}
          </option>
        </select>
      </FormField>

      <FormField
        v-for="field in selectedProvider?.options || []"
        :key="field.key"
        :label="field.label"
        :span="field.span"
      >
        <InputGroup v-if="field.key === 'tunnel_token'">
          <InputGroupInput
            v-model="draft.network.options[field.key]"
            :disabled="locked"
            :type="tunnelTokenVisible ? 'text' : 'password'"
            autocomplete="off"
          />
          <InputGroupButton
            :aria-label="tunnelTokenVisible ? '隐藏隧道令牌' : '显示隧道令牌'"
            :aria-pressed="tunnelTokenVisible"
            :title="tunnelTokenVisible ? '隐藏隧道令牌' : '显示隧道令牌'"
            @click="tunnelTokenVisible = !tunnelTokenVisible"
          ><EyeOff v-if="tunnelTokenVisible" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
        </InputGroup>
        <input
          v-else
          v-model.trim="draft.network.options[field.key]"
          :disabled="locked"
          :type="field.secret ? 'password' : 'text'"
          autocomplete="off"
        />
      </FormField>

      <FormField label="OAuth 密码">
        <InputGroup>
          <InputGroupInput
            v-model="draft.oauth_password"
            :disabled="locked"
            :type="oauthPasswordVisible ? 'text' : 'password'"
            autocomplete="off"
          />
          <InputGroupButton
            :aria-label="oauthPasswordVisible ? '隐藏 OAuth 密码' : '显示 OAuth 密码'"
            :aria-pressed="oauthPasswordVisible"
            :title="oauthPasswordVisible ? '隐藏 OAuth 密码' : '显示 OAuth 密码'"
            @click="emit('toggleOAuthPassword')"
          ><EyeOff v-if="oauthPasswordVisible" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
        </InputGroup>
      </FormField>

      <PermissionModeField v-model="draft.permission_mode" :disabled="locked" />

      <CheckField span="2"><input v-model="draft.remember_secrets" type="checkbox" /><span>在本机保存网络令牌与 OAuth 密码</span></CheckField>
      <div class="col-span-2 min-w-0">
        <BodyPluginEditor :locked="locked" />
      </div>
    </FormGrid>

    <div v-if="runtimeUrl" class="mt-4 flex items-center gap-2 rounded-md border border-border bg-secondary/50 px-3 py-[9px]">
      <code class="min-w-0 flex-1 truncate text-[11px] font-medium text-blue-600 dark:text-blue-400">{{ runtimeUrl }}</code>
      <Button variant="outline" size="icon" class="h-7 w-7 text-muted-foreground" @click="emit('copyUrl', runtimeUrl)">
        <Check v-if="copiedUrl === runtimeUrl" :size="13" /><Copy v-else :size="13" />
      </Button>
    </div>

    <div class="mt-4 flex justify-between gap-2 border-t border-border pt-3.5">
      <div class="ml-auto flex items-center gap-2">
        <Button
          :variant="selectedRunning ? 'destructiveOutline' : 'default'"
          size="sm"
          :disabled="busy || lifecycleBusy"
          @click="emit('toggleRunning')"
        >
          <Square v-if="selectedRunning" :size="13" />
          <Play v-else :size="13" />
          {{ lifecycleBusy ? (selectedRunning ? '停止中…' : '启动中…') : (selectedRunning ? '停止' : '启动') }}
        </Button>
        <Button variant="outline" size="sm" :disabled="busy || lifecycleBusy || locked" @click="emit('save')">
          保存
        </Button>
      </div>
    </div>
  </section>
</template>
