import { inject, provide, type InjectionKey } from 'vue'
import type { useWorkflowEditor } from '../../composables/useWorkflowEditor'

export type WorkflowEditor = ReturnType<typeof useWorkflowEditor>

const workflowEditorKey: InjectionKey<WorkflowEditor> = Symbol('workflow-editor')

export function provideWorkflowEditor(editor: WorkflowEditor) {
  provide(workflowEditorKey, editor)
}

export function useWorkflowEditorContext(): WorkflowEditor {
  const editor = inject(workflowEditorKey)
  if (!editor) throw new Error('Workflow editor context is not available')
  return editor
}
