<script setup lang="ts">
import { FormField } from '@/components/ui/form'
import type { MCPDiscoveredToolDto } from '../types'

defineProps<{ tools: MCPDiscoveredToolDto[] }>()
const healthTool = defineModel<string>({ required: true })
</script>

<template>
  <FormField>
    <span>深度健康检查工具</span>
    <select v-model="healthTool">
      <option value="">不验证应用后端</option>
      <option
        v-for="tool in tools.filter(item => item.annotations?.readOnlyHint === true && item.annotations?.destructiveHint !== true)"
        :key="tool.name"
        :value="tool.name"
      >
        {{ tool.name }}
      </option>
    </select>
    <small class="text-[10px] font-normal text-muted-foreground">
      仅允许 MCP 声明为只读且非破坏性的工具。用于验证 MCP 进程背后的应用后端是否真的可达，例如 Blender Addon Server。
    </small>
  </FormField>
</template>
