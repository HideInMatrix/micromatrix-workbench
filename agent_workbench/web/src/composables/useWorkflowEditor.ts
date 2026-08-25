import { computed, nextTick, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from 'vue'
import { desktopApi } from '../api/desktop'
import { emptyWorkflowCatalog } from './workflowEditorModels'
import {
  canvasToWorkflow,
  workflowToCanvas,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from '../lib/workflowGraph'
import type {
  WorkbenchCatalogDto,
  WorkbenchTargetDto,
  WorkflowApprovalDto,
  WorkflowDefinitionDto,
  WorkflowRunDto,
  WorkflowValidationDto,
} from '../types'

interface WorkflowEditorState {
  targets: Ref<WorkbenchTargetDto[]>
  targetId: Ref<string>
  catalog: Ref<WorkbenchCatalogDto>
  workflowId: Ref<string>
  workflowName: Ref<string>
  workflowDescription: Ref<string>
  workflowVersion: Ref<number>
  workflowScope: Ref<'built-in' | 'global' | 'workspace'>
  workflowInputsSchema: Ref<Record<string, unknown>>
  workflowTags: Ref<string[]>
  workflowMetadata: Ref<Record<string, unknown>>
  entryNodeId: Ref<string>
  nodes: Ref<WorkflowCanvasNode[]>
  edges: Ref<WorkflowCanvasEdge[]>
  validation: Ref<WorkflowValidationDto | null>
  runs: Ref<WorkflowRunDto[]>
  approvals: Ref<WorkflowApprovalDto[]>
  selectedRunId: Ref<string>
  busy: Ref<boolean>
  error: Ref<string>
  notice: Ref<string>
  history: Ref<string[]>
  historyIndex: Ref<number>
  timers: { poll: number; history: number; historyApplying: boolean; historyReady: boolean }
}

interface WorkflowEditorContext extends WorkflowEditorState {
  canUndo: ComputedRef<boolean>
  canRedo: ComputedRef<boolean>
  selectedTarget: ComputedRef<WorkbenchTargetDto | null>
  selectedRun: ComputedRef<WorkflowRunDto | null>
  workflowApprovals: ComputedRef<WorkflowApprovalDto[]>
}

function createWorkflowEditorState(): WorkflowEditorState {
  return {
    targets: ref<WorkbenchTargetDto[]>([]), targetId: ref(''), catalog: ref<WorkbenchCatalogDto>(emptyWorkflowCatalog()), workflowId: ref(''),
    workflowName: ref(''), workflowDescription: ref(''), workflowVersion: ref(1), workflowScope: ref<'built-in' | 'global' | 'workspace'>('workspace'),
    workflowInputsSchema: ref<Record<string, unknown>>({ type: 'object', properties: {}, additionalProperties: true }),
    workflowTags: ref<string[]>([]), workflowMetadata: ref<Record<string, unknown>>({}), entryNodeId: ref(''),
    nodes: ref<WorkflowCanvasNode[]>([]), edges: ref<WorkflowCanvasEdge[]>([]),
    validation: ref<WorkflowValidationDto | null>(null), runs: ref<WorkflowRunDto[]>([]), approvals: ref<WorkflowApprovalDto[]>([]),
    selectedRunId: ref(''), busy: ref(false),
    error: ref(''), notice: ref(''), history: ref<string[]>([]), historyIndex: ref(-1),
    timers: { poll: 0, history: 0, historyApplying: false, historyReady: false },
  }
}

function createWorkflowEditorContext(state: WorkflowEditorState): WorkflowEditorContext {
  const canUndo = computed(() => state.historyIndex.value > 0)
  const canRedo = computed(() => state.historyIndex.value >= 0 && state.historyIndex.value < state.history.value.length - 1)
  const selectedTarget = computed(() => state.targets.value.find(item => item.target_id === state.targetId.value) ?? null)
  const selectedRun = computed(() => state.runs.value.find(item => item.run_id === state.selectedRunId.value) ?? null)
  const workflowApprovals = computed(() => {
    const serverId = selectedTarget.value?.server_id
    return state.approvals.value.filter(item => item.server_id === serverId && (
      !state.workflowId.value || state.runs.value.some(run => run.run_id === item.run_id && run.workflow_id === state.workflowId.value)
    ))
  })
  return { ...state, canUndo, canRedo, selectedTarget, selectedRun, workflowApprovals }
}

function definition(context: WorkflowEditorContext): WorkflowDefinitionDto {
  return canvasToWorkflow({
    id: context.workflowId.value,
    name: context.workflowName.value,
    description: context.workflowDescription.value,
    version: context.workflowVersion.value,
    entryNodeId: context.entryNodeId.value,
    inputsSchema: context.workflowInputsSchema.value,
    tags: context.workflowTags.value,
    metadata: context.workflowMetadata.value,
  }, context.nodes.value, context.edges.value)
}

function historySnapshot(context: WorkflowEditorContext): string {
  return JSON.stringify({ ...definition(context), scope: context.workflowScope.value })
}

function resetHistory(context: WorkflowEditorContext) {
  window.clearTimeout(context.timers.history)
  context.timers.history = 0
  context.history.value = [historySnapshot(context)]
  context.historyIndex.value = 0
  context.timers.historyReady = true
}

function pushHistory(context: WorkflowEditorContext) {
  if (!context.timers.historyReady || context.timers.historyApplying) return
  const snapshot = historySnapshot(context)
  if (context.history.value[context.historyIndex.value] === snapshot) return
  context.history.value = context.history.value.slice(0, context.historyIndex.value + 1)
  context.history.value.push(snapshot)
  if (context.history.value.length > 100) context.history.value.shift()
  context.historyIndex.value = context.history.value.length - 1
}

function scheduleHistory(context: WorkflowEditorContext) {
  if (!context.timers.historyReady || context.timers.historyApplying) return
  window.clearTimeout(context.timers.history)
  context.timers.history = window.setTimeout(() => pushHistory(context), 140)
}

function applyRunState(context: WorkflowEditorContext) {
  const run = context.selectedRun.value
  for (const node of context.nodes.value) {
    let status = 'idle'
    if (run) {
      status = run.node_states[node.id]?.status ?? (run.engine_state.ready.includes(node.id) ? 'ready' : 'idle')
    }
    node.data.status = status
  }
}

function applyDefinition(context: WorkflowEditorContext, value: WorkflowDefinitionDto, reset = true) {
  context.workflowId.value = value.id
  context.workflowName.value = value.name
  context.workflowDescription.value = value.description
  context.workflowVersion.value = value.version
  context.workflowScope.value = value.scope ?? 'workspace'
  context.workflowInputsSchema.value = { ...value.inputs_schema }
  context.workflowTags.value = [...value.tags]
  context.workflowMetadata.value = { ...value.metadata }
  context.entryNodeId.value = value.entry_node_id
  const canvas = workflowToCanvas(value)
  context.nodes.value = canvas.nodes
  context.edges.value = canvas.edges
  context.validation.value = null
  context.notice.value = ''
  applyRunState(context)
  if (reset) resetHistory(context)
}

function newWorkflow(context: WorkflowEditorContext) {
  const suffix = Date.now().toString(36)
  context.workflowId.value = `workflow-${suffix}`
  context.workflowName.value = '新 Workflow'
  context.workflowDescription.value = ''
  context.workflowVersion.value = 1
  context.workflowScope.value = 'workspace'
  context.workflowInputsSchema.value = { type: 'object', properties: {}, additionalProperties: true }
  context.workflowTags.value = []
  context.workflowMetadata.value = {}
  context.entryNodeId.value = ''
  context.nodes.value = []
  context.edges.value = []
  context.validation.value = null
  context.selectedRunId.value = ''
  context.notice.value = '新 Workflow 尚未保存。'
  resetHistory(context)
}

function validateRequiredMetadata(context: WorkflowEditorContext): boolean {
  const description = context.workflowDescription.value.trim()
  if (!description) {
    context.error.value = '请输入 Workflow 描述。'
    context.notice.value = ''
    return false
  }
  context.workflowDescription.value = description
  return true
}

async function applyHistorySnapshot(context: WorkflowEditorContext, snapshot: string) {
  context.timers.historyApplying = true
  try {
    applyDefinition(context, JSON.parse(snapshot) as WorkflowDefinitionDto, false)
    await nextTick()
  } finally {
    context.timers.historyApplying = false
  }
}

async function undo(context: WorkflowEditorContext) {
  if (!context.canUndo.value) return
  window.clearTimeout(context.timers.history)
  context.historyIndex.value -= 1
  await applyHistorySnapshot(context, context.history.value[context.historyIndex.value])
  context.notice.value = '已撤销上一步 Workflow 编辑。'
}

async function redo(context: WorkflowEditorContext) {
  if (!context.canRedo.value) return
  window.clearTimeout(context.timers.history)
  context.historyIndex.value += 1
  await applyHistorySnapshot(context, context.history.value[context.historyIndex.value])
  context.notice.value = '已恢复下一步 Workflow 编辑。'
}

async function refreshCatalog(context: WorkflowEditorContext) {
  if (!context.targetId.value) {
    context.catalog.value = emptyWorkflowCatalog()
    return context.catalog.value
  }
  context.catalog.value = await desktopApi.workbenchCatalog(context.targetId.value)
  return context.catalog.value
}

async function refreshRuntimeState(context: WorkflowEditorContext) {
  if (!context.targetId.value) return
  const [runs, approvals] = await Promise.all([
    desktopApi.listWorkbenchRuns(context.targetId.value),
    desktopApi.listWorkflowApprovals(),
  ])
  context.runs.value = runs
  context.approvals.value = approvals
  if (context.selectedRunId.value && !runs.some(item => item.run_id === context.selectedRunId.value)) context.selectedRunId.value = ''
  if (!context.selectedRunId.value && context.workflowId.value) {
    context.selectedRunId.value = runs.find(item => item.workflow_id === context.workflowId.value)?.run_id ?? ''
  }
  applyRunState(context)
}

async function loadWorkflow(context: WorkflowEditorContext, workflowId: string) {
  if (!context.targetId.value || !workflowId) return
  context.busy.value = true
  context.error.value = ''
  try {
    const value = await desktopApi.workbenchWorkflow(context.targetId.value, workflowId)
    applyDefinition(context, value)
    context.selectedRunId.value = context.runs.value.find(run => run.workflow_id === workflowId)?.run_id ?? ''
    applyRunState(context)
  } catch (reason) {
    context.error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    context.busy.value = false
  }
}

async function loadTarget(context: WorkflowEditorContext, targetId: string) {
  context.targetId.value = targetId
  context.error.value = ''
  if (!targetId) {
    context.catalog.value = emptyWorkflowCatalog()
    newWorkflow(context)
    return
  }
  context.busy.value = true
  try {
    await refreshCatalog(context)
    await refreshRuntimeState(context)
    const preferred = context.catalog.value.workflows.find(item => item.id === context.workflowId.value) ?? context.catalog.value.workflows[0]
    if (preferred) await loadWorkflow(context, preferred.id)
    else newWorkflow(context)
  } catch (reason) {
    context.error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    context.busy.value = false
  }
}

async function refreshTargets(context: WorkflowEditorContext) {
  context.targets.value = await desktopApi.listWorkbenchTargets()
  if (!context.targetId.value || !context.targets.value.some(item => item.target_id === context.targetId.value)) {
    context.targetId.value = context.targets.value[0]?.target_id ?? ''
  }
  if (context.targetId.value) await loadTarget(context, context.targetId.value)
}

async function validateWorkflow(context: WorkflowEditorContext) {
  if (!context.targetId.value || !validateRequiredMetadata(context)) return null
  context.busy.value = true
  context.error.value = ''
  try {
    context.validation.value = await desktopApi.validateWorkbenchWorkflow(context.targetId.value, definition(context))
    context.notice.value = context.validation.value.ok
      ? '后端 Validator 验证通过。'
      : `验证失败：${context.validation.value.errors.length} 个错误。`
    return context.validation.value
  } catch (reason) {
    context.error.value = reason instanceof Error ? reason.message : String(reason)
    return null
  } finally {
    context.busy.value = false
  }
}

async function saveWorkflow(context: WorkflowEditorContext) {
  if (!context.targetId.value || !validateRequiredMetadata(context)) return null
  context.busy.value = true
  context.error.value = ''
  try {
    const current = context.catalog.value.workflows.find(item => item.id === context.workflowId.value)
    const expectedVersion = current?.scope === 'workspace' ? current.version : 0
    const result = await desktopApi.saveWorkbenchWorkflow(context.targetId.value, definition(context), expectedVersion)
    context.validation.value = result
    if (!result.ok || !result.saved) {
      context.notice.value = `保存失败：${result.errors.length} 个验证错误。`
      return result
    }
    applyDefinition(context, result.workflow, false)
    await refreshCatalog(context)
    context.notice.value = `Workflow 已保存为 v${result.workflow.version}。`
    return result
  } catch (reason) {
    context.error.value = reason instanceof Error ? reason.message : String(reason)
    return null
  } finally {
    context.busy.value = false
  }
}

async function removeWorkflow(context: WorkflowEditorContext) {
  if (!context.targetId.value || context.workflowScope.value !== 'workspace') return false
  context.busy.value = true
  try {
    const deleted = await desktopApi.deleteWorkbenchWorkflow(context.targetId.value, context.workflowId.value)
    await refreshCatalog(context)
    if (deleted) {
      const next = context.catalog.value.workflows[0]
      if (next) await loadWorkflow(context, next.id)
      else newWorkflow(context)
      context.notice.value = 'Workflow 已删除，列表已刷新。'
    }
    return deleted
  } finally {
    context.busy.value = false
  }
}

async function respondApproval(context: WorkflowEditorContext, requestId: string, approved: boolean) {
  const ok = await desktopApi.respondWorkflowApproval(requestId, approved)
  context.notice.value = ok
    ? '审批决策已签名发送，等待 AI 调用 workflow_continue 继续 Run。'
    : '审批响应失败或请求已失效。'
  await refreshRuntimeState(context)
  return ok
}

function startPolling(context: WorkflowEditorContext) {
  window.clearInterval(context.timers.poll)
  context.timers.poll = window.setInterval(() => void refreshRuntimeState(context), 1500)
}

function stopPolling(context: WorkflowEditorContext) {
  window.clearInterval(context.timers.poll)
  context.timers.poll = 0
}

function publicState(context: WorkflowEditorContext) {
  const { timers: _timers, history: _history, historyIndex: _historyIndex, approvals: _approvals, ...state } = context
  return state
}

function publicActions(context: WorkflowEditorContext) {
  return {
    definition: () => definition(context),
    newWorkflow: () => newWorkflow(context),
    refreshTargets: () => refreshTargets(context),
    loadTarget: (id: string) => loadTarget(context, id),
    loadWorkflow: (id: string) => loadWorkflow(context, id),
    validate: () => validateWorkflow(context),
    save: () => saveWorkflow(context),
    remove: () => removeWorkflow(context),
    refreshRuntimeState: () => refreshRuntimeState(context),
    respondApproval: (id: string, approved: boolean) => respondApproval(context, id, approved),
    undo: () => undo(context),
    redo: () => redo(context),
    startPolling: () => startPolling(context),
    stopPolling: () => stopPolling(context),
  }
}

export function useWorkflowEditor() {
  const context = createWorkflowEditorContext(createWorkflowEditorState())
  watch(() => historySnapshot(context), () => scheduleHistory(context), { deep: true })
  onBeforeUnmount(() => {
    stopPolling(context)
    window.clearTimeout(context.timers.history)
  })
  return { ...publicState(context), ...publicActions(context) }
}
