<script setup lang="ts">
import { computed } from 'vue'
import { Check, Copy, Eye, EyeOff, FolderOpen, Play, RotateCcw, Square, Trash2 } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { CheckField, FormField, FormGrid } from '@/components/ui/form'
import { InputGroup, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import type { NetworkProviderDto, RuntimeDraft } from '../../types'
import PermissionModeField from './PermissionModeField.vue'

const draft = defineModel<RuntimeDraft>('draft', { required: true })
const tunnelTokenVisible = defineModel<boolean>('tunnelTokenVisible', { required: true })

const props = defineProps<{
  locked: boolean
  busy: boolean
  lifecycleBusy: boolean
  lifecycleAction: 'start' | 'stop' | null
  selectedRunning: boolean
  copiedUrl: string
  runtimeUrl: string
  networkProviders: NetworkProviderDto[]
  oauthPasswordVisible: boolean
}>()

const selectedProvider = computed(() => (
  props.networkProviders.find(item => item.key === draft.value.network.provider)
))

function secretConfigured(key: string) {
  return draft.value.network.configured_secrets.includes(key)
}

function updateNetworkChoice(key: string, event: Event) {
  draft.value.network.options[key] = (event.target as HTMLSelectElement).value
}

// Use the emitted new value: a forwarded native input listener can run before
// v-model updates, misclassifying a first paste as an unchanged empty secret.
function updateNetworkSecret(key: string, value: string) {
  draft.value.network.options[key] = value
  draft.value.network.secret_actions[key] = value ? 'set' : 'unchanged'
}

function toggleNetworkSecretClear(key: string) {
  const clearing = draft.value.network.secret_actions[key] === 'clear'
  draft.value.network.options[key] = ''
  draft.value.network.secret_actions[key] = clearing ? 'unchanged' : 'clear'
}

function updateOAuthPassword(value: string) {
  draft.value.oauth_password = value
  draft.value.oauth_password_action = value ? 'set' : 'unchanged'
}

function toggleOAuthPasswordClear() {
  const clearing = draft.value.oauth_password_action === 'clear'
  draft.value.oauth_password = ''
  draft.value.oauth_password_action = clearing ? 'unchanged' : 'clear'
}

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
    <h2 class="mb-4 text-sm font-medium">Runtime 设置</h2>

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
        <div v-if="field.secret" class="grid gap-1.5">
          <InputGroup>
            <InputGroupInput
              :model-value="draft.network.options[field.key]"
              :disabled="locked || draft.network.secret_actions[field.key] === 'clear'"
              :type="tunnelTokenVisible ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="留空则保留现有值"
              @update:model-value="updateNetworkSecret(field.key, $event)"
            />
            <InputGroupButton
              :aria-label="tunnelTokenVisible ? '隐藏网络密钥' : '显示网络密钥'"
              :aria-pressed="tunnelTokenVisible"
              :title="tunnelTokenVisible ? '隐藏网络密钥' : '显示网络密钥'"
              @click="tunnelTokenVisible = !tunnelTokenVisible"
            ><EyeOff v-if="tunnelTokenVisible" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
            <InputGroupButton
              :disabled="locked || (!secretConfigured(field.key) && !draft.network.options[field.key])"
              :aria-label="draft.network.secret_actions[field.key] === 'clear' ? '撤销清除网络密钥' : '清除网络密钥'"
              :title="draft.network.secret_actions[field.key] === 'clear' ? '撤销清除' : '保存时清除'"
              @click="toggleNetworkSecretClear(field.key)"
            ><RotateCcw v-if="draft.network.secret_actions[field.key] === 'clear'" :size="15" /><Trash2 v-else :size="15" /></InputGroupButton>
          </InputGroup>
        </div>
        <select
          v-else-if="field.choices"
          :value="draft.network.options[field.key] || field.default_value"
          :disabled="locked"
          @change="updateNetworkChoice(field.key, $event)"
        >
          <option v-for="choice in field.choices" :key="choice.value" :value="choice.value">
            {{ choice.label }}
          </option>
        </select>
        <input
          v-else
          v-model.trim="draft.network.options[field.key]"
          :disabled="locked"
          type="text"
          autocomplete="off"
        />
        <details v-if="field.description" class="text-xs font-normal text-muted-foreground">
          <summary class="cursor-pointer">配置说明</summary>
          <p class="mt-1 leading-5">{{ field.description }}</p>
        </details>
      </FormField>

      <FormField label="OAuth 密码">
        <div class="grid gap-1.5">
          <InputGroup>
            <InputGroupInput
              :model-value="draft.oauth_password"
              :disabled="locked || draft.oauth_password_action === 'clear'"
              :type="oauthPasswordVisible ? 'text' : 'password'"
              autocomplete="new-password"
              placeholder="留空则保留现有值"
              @update:model-value="updateOAuthPassword"
            />
            <InputGroupButton
              :aria-label="oauthPasswordVisible ? '隐藏 OAuth 密码' : '显示 OAuth 密码'"
              :aria-pressed="oauthPasswordVisible"
              :title="oauthPasswordVisible ? '隐藏 OAuth 密码' : '显示 OAuth 密码'"
              @click="emit('toggleOAuthPassword')"
            ><EyeOff v-if="oauthPasswordVisible" :size="15" /><Eye v-else :size="15" /></InputGroupButton>
            <InputGroupButton
              :disabled="locked || (!draft.oauth_password_configured && !draft.oauth_password)"
              :aria-label="draft.oauth_password_action === 'clear' ? '撤销清除 OAuth 密码' : '清除 OAuth 密码'"
              :title="draft.oauth_password_action === 'clear' ? '撤销清除' : '保存时清除'"
              @click="toggleOAuthPasswordClear"
            ><RotateCcw v-if="draft.oauth_password_action === 'clear'" :size="15" /><Trash2 v-else :size="15" /></InputGroupButton>
          </InputGroup>
        </div>
      </FormField>

      <PermissionModeField v-model="draft.permission_mode" :disabled="locked" />

      <CheckField span="2"><input v-model="draft.remember_secrets" type="checkbox" /><span>在本机保存网络令牌与 OAuth 密码</span></CheckField>
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
          :disabled="busy || lifecycleAction === 'stop'"
          @click="emit('toggleRunning')"
        >
          <Square v-if="selectedRunning || lifecycleAction === 'start'" :size="13" />
          <Play v-else :size="13" />
          {{ lifecycleAction === 'stop' ? '停止中…' : lifecycleAction === 'start' ? '取消启动' : selectedRunning ? '停止' : '启动' }}
        </Button>
        <Button variant="outline" size="sm" :disabled="busy || lifecycleBusy || locked" @click="emit('save')">
          保存
        </Button>
      </div>
    </div>
  </section>
</template>
