import type {
  ToolchainProposal,
  ToolchainRegistration,
  BootstrapDto,
  CapabilityCatalogDto,
  DesktopBridge,
  LogEntryDto,
  MCPConnectionDefinitionDto,
  MCPConnectionProbeDto,
  MCPConnectionValidationDto,
  NetworkProviderDto,
  PermissionRequestDto,
  SkillDefinitionDto,
  SkillValidationDto,
  ReleaseDto,
  UpdateStatusDto,
  UpdateCheckStateDto,
  UpdateInstallImpactDto,
  ServerDraft,
  ServerDto,
} from '../types'

let bridgePromise: Promise<DesktopBridge> | null = null

function isBridgeReady(api: Partial<DesktopBridge> | undefined): api is DesktopBridge {
  return Boolean(
    api
      && typeof api.bootstrap === 'function'
      && typeof api.get_app_version === 'function'
      && typeof api.list_servers === 'function',
  )
}

function bridge(): Promise<DesktopBridge> {
  if (isBridgeReady(window.pywebview?.api)) return Promise.resolve(window.pywebview.api)
  if (bridgePromise) return bridgePromise

  bridgePromise = new Promise<DesktopBridge>((resolve) => {
    const resolveWhenReady = () => {
      const api = window.pywebview?.api
      if (isBridgeReady(api)) {
        resolve(api)
        return
      }
      window.setTimeout(resolveWhenReady, 10)
    }

    window.addEventListener('pywebviewready', resolveWhenReady, { once: true })
    resolveWhenReady()
  })
  return bridgePromise
}

export const desktopApi = {
  async bootstrap(): Promise<BootstrapDto> {
    return (await bridge()).bootstrap()
  },
  async inspectToolchain(program: string, executable: string, roots: string[]): Promise<ToolchainProposal> {
    return (await bridge()).inspect_toolchain(program, executable, roots)
  },
  async registerToolchain(program: string, executable: string, roots: string[]): Promise<ToolchainRegistration> {
    return (await bridge()).register_toolchain(program, executable, roots)
  },
  async appVersion(): Promise<string> {
    return (await bridge()).get_app_version()
  },
  async selectedServerId(): Promise<string> {
    return (await bridge()).get_selected_server_id()
  },
  async updateDownloadProxy(): Promise<string> {
    return (await bridge()).get_update_download_proxy()
  },
  async saveUpdateDownloadProxy(prefix: string): Promise<string> {
    return (await bridge()).save_update_download_proxy(prefix)
  },
  async networkProviders(): Promise<NetworkProviderDto[]> {
    return (await bridge()).list_network_providers()
  },
  async listServers(): Promise<ServerDto[]> {
    return (await bridge()).list_servers()
  },
  async nextPort(): Promise<number> {
    return (await bridge()).get_next_port()
  },
  async selectServer(serverId: string): Promise<boolean> {
    return (await bridge()).select_server(serverId)
  },
  async createServer(payload: ServerDraft): Promise<ServerDto> {
    return (await bridge()).create_server(payload)
  },
  async updateServer(serverId: string, payload: ServerDraft): Promise<ServerDto> {
    return (await bridge()).update_server(serverId, payload)
  },
  async deleteServer(serverId: string): Promise<boolean> {
    return (await bridge()).delete_server(serverId)
  },
  async startServer(serverId: string, payload?: ServerDraft): Promise<ServerDto> {
    return (await bridge()).start_server(serverId, payload)
  },
  async stopServer(serverId: string): Promise<ServerDto> {
    return (await bridge()).stop_server(serverId)
  },
  async setServerEnabled(serverId: string, enabled: boolean): Promise<ServerDto> {
    return (await bridge()).set_server_enabled(serverId, enabled)
  },
  async listPermissionRequests(): Promise<PermissionRequestDto[]> {
    return (await bridge()).list_permission_requests()
  },
  async respondPermissionRequest(requestId: string, decision: 'deny' | 'once' | 'session' | 'resource_session' | 'remember'): Promise<boolean> {
    return (await bridge()).respond_permission_request(requestId, decision)
  },
  async stopAllDesktopInput(): Promise<{ requested: number; stopped: number; results: Record<string, boolean> }> {
    return (await bridge()).stop_all_desktop_input()
  },
  async capabilityCatalog(): Promise<CapabilityCatalogDto> {
    return (await bridge()).get_workbench_capability_catalog()
  },
  async workbenchMCPConnection(connectionId: string): Promise<MCPConnectionDefinitionDto> {
    return (await bridge()).get_workbench_mcp_connection(connectionId)
  },
  async validateWorkbenchMCPConnection(connection: MCPConnectionDefinitionDto): Promise<MCPConnectionValidationDto> {
    return (await bridge()).validate_workbench_mcp_connection(connection)
  },
  async saveWorkbenchMCPConnection(connection: MCPConnectionDefinitionDto, expectedVersion: number): Promise<MCPConnectionValidationDto> {
    return (await bridge()).save_workbench_mcp_connection(connection, expectedVersion)
  },
  async deleteWorkbenchMCPConnection(connectionId: string): Promise<boolean> {
    return (await bridge()).delete_workbench_mcp_connection(connectionId)
  },
  async testWorkbenchMCPConnection(connectionId: string, timeoutSeconds = 8, deep = false): Promise<MCPConnectionProbeDto> {
    return (await bridge()).test_workbench_mcp_connection(connectionId, timeoutSeconds, deep)
  },
  async discoverWorkbenchMCPConnectionTools(connectionId: string, timeoutSeconds = 8): Promise<MCPConnectionProbeDto> {
    return (await bridge()).discover_workbench_mcp_connection_tools(connectionId, timeoutSeconds)
  },
  async workbenchSkill(skillId: string): Promise<SkillDefinitionDto> {
    return (await bridge()).get_workbench_skill(skillId)
  },
  async validateWorkbenchSkill(skill: SkillDefinitionDto): Promise<SkillValidationDto> {
    return (await bridge()).validate_workbench_skill(skill)
  },
  async saveWorkbenchSkill(skill: SkillDefinitionDto, expectedVersion: number): Promise<SkillValidationDto> {
    return (await bridge()).save_workbench_skill(skill, expectedVersion)
  },
  async deleteWorkbenchSkill(skillId: string): Promise<boolean> {
    return (await bridge()).delete_workbench_skill(skillId)
  },
  async logs(after = 0): Promise<{ cursor: number; entries: LogEntryDto[] }> {
    return (await bridge()).get_logs(after)
  },
  async clearLogs(): Promise<number> {
    return (await bridge()).clear_logs()
  },
  async chooseWorkspace(initial = ''): Promise<string> {
    return (await bridge()).choose_workspace(initial)
  },
  async chooseFile(initial = ''): Promise<string> {
    return (await bridge()).choose_file(initial)
  },
  async detectExecutable(product: string, configured = '') {
    return (await bridge()).detect_executable(product, configured)
  },
  async updateCheckState(): Promise<UpdateCheckStateDto> {
    return (await bridge()).get_update_check_state()
  },
  async updateInstallImpact(): Promise<UpdateInstallImpactDto> {
    return (await bridge()).get_update_install_impact()
  },
  async checkUpdate(force = true): Promise<ReleaseDto> {
    return (await bridge()).check_update(force)
  },
  async startUpdate(): Promise<UpdateStatusDto> {
    return (await bridge()).start_update()
  },
  async updateStatus(): Promise<UpdateStatusDto> {
    return (await bridge()).update_status()
  },
  async installUpdate(confirmedServices: string[]): Promise<UpdateStatusDto> {
    return (await bridge()).install_update(confirmedServices)
  },
  async openExternal(url: string): Promise<boolean> {
    return (await bridge()).open_external(url)
  },
}
