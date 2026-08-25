import type { WorkbenchCatalogDto } from '../types'

export function emptyWorkflowCatalog(): WorkbenchCatalogDto {
  return {
    target: { target_id: '', server_id: '', service_name: '', profile_name: '', workspace: '', running: false },
    skills: [],
    tools: [],
    effective_tools: [],
    mcp_connections: [],
    workflows: [],
    capabilities: [],
  }
}
