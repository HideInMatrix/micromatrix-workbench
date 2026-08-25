import { FileOutput, GitBranch, ShieldCheck, Sparkles, Wrench } from '@lucide/vue'
import type { WorkflowEdgeDto, WorkflowNodeKind } from '../../types'

export type WorkflowNodeRole = 'input' | 'process' | 'output'

export const nodeRoles: WorkflowNodeRole[] = ['input', 'process', 'output']

export const nodeDefinitions: Record<WorkflowNodeKind, { label: string; description: string }> = {
  skill: { label: 'Skill', description: '让宿主 AI 使用用户定义的方法、约束与知识' },
  tool: { label: 'Tool', description: '执行 System Tool 或外部 MCP Tool' },
  approval: { label: 'Approval', description: '等待 Desktop 用户签名批准' },
  condition: { label: 'Condition', description: '使用受限表达式选择分支' },
  artifact: { label: 'Artifact', description: '保存已有节点输出到 Run Artifact' },
}

export const nodeGroups: Array<{
  label: string
  description: string
  kinds: WorkflowNodeKind[]
}> = [
  { label: 'AI Knowledge', description: '为宿主 AI 提供方法、约束与知识，不在 Workbench 内部做任务决策。', kinds: ['skill'] },
  { label: 'Actions', description: '执行确定性的本地或外部能力。', kinds: ['tool'] },
  { label: 'Flow Control', description: '控制分支、人工边界与结果沉淀。', kinds: ['condition', 'approval', 'artifact'] },
]

export function nodeRole(nodeId: string, entryNodeId: string, config: Record<string, unknown>): WorkflowNodeRole {
  if (nodeId === entryNodeId) return 'input'
  return config.node_role === 'output' ? 'output' : 'process'
}

export function nodeRoleLabel(role: WorkflowNodeRole): string {
  return role === 'input' ? '输入' : role === 'output' ? '输出' : '处理'
}

export function withoutNodeRole(config: Record<string, unknown>): Record<string, unknown> {
  const next = { ...config }
  delete next.node_role
  return next
}

export function nodeIcon(kind: WorkflowNodeKind) {
  return { skill: Sparkles, tool: Wrench, approval: ShieldCheck, condition: GitBranch, artifact: FileOutput }[kind]
}

export function nodeKindBorderClass(kind: WorkflowNodeKind): string {
  return {
    skill: 'border-violet-500/80 dark:border-violet-400/80',
    tool: 'border-blue-500/80 dark:border-blue-400/80',
    approval: 'border-amber-500/80 dark:border-amber-400/80',
    condition: 'border-orange-500/80 dark:border-orange-400/80',
    artifact: 'border-emerald-500/80 dark:border-emerald-400/80',
  }[kind]
}

export function nodeStateClass(status: string, selected: boolean): string {
  const selectedClass = selected ? 'ring-2 ring-primary/25 ring-offset-1 ring-offset-background' : ''
  if (status === 'succeeded' || status === 'approved') return `bg-green-500/10 ${selectedClass}`
  if (status === 'failed' || status === 'rejected') return `bg-destructive/10 ${selectedClass}`
  if (status === 'waiting_model' || status === 'waiting_approval' || status === 'ready') return `bg-yellow-400/10 ${selectedClass}`
  return selected ? `bg-primary/5 ${selectedClass}` : 'bg-card'
}

export function defaultEdgeCondition(kind: WorkflowNodeKind): WorkflowEdgeDto['condition'] {
  if (kind === 'approval') return 'approved'
  if (kind === 'condition') return 'true'
  return 'success'
}
