import {
  createEditTool,
  createFindTool,
  createGrepTool,
  createLsTool,
  createReadTool,
  createWriteTool,
} from "@earendil-works/pi-coding-agent";
import type { AgentTool } from "@earendil-works/pi-agent-core";
import { registerAgentTools } from "@micromatrix/pi-body";
import type { BodyPlugin } from "@micromatrix/plugin-kit";

import { WorkspaceBoundary } from "./boundary.js";

export { WorkspaceBoundary, WorkspaceBoundaryError } from "./boundary.js";

function guardExistingPath(tool: AgentTool, boundary: WorkspaceBoundary): AgentTool {
  return {
    ...tool,
    async execute(toolCallId, params, signal, onUpdate) {
      const value = params as { readonly path?: unknown };
      const path = typeof value.path === "string" ? value.path : ".";
      await boundary.existing(path);
      return tool.execute(toolCallId, params, signal, onUpdate);
    },
  };
}

export function createWorkspacePlugin(): BodyPlugin {
  return {
    id: "workspace",
    displayName: "Pi workspace tools",
    createTools: ({ workspace }) => {
      const boundary = new WorkspaceBoundary(workspace);
      return [
        createReadTool(workspace, { operations: boundary.readOperations() }),
        createGrepTool(workspace, { operations: boundary.grepOperations() }),
        guardExistingPath(createFindTool(workspace), boundary),
        createLsTool(workspace, { operations: boundary.lsOperations() }),
        createEditTool(workspace, { operations: boundary.editOperations() }),
        createWriteTool(workspace, { operations: boundary.writeOperations() }),
      ];
    },
    installPiExtension(pi, context) {
      registerAgentTools(pi, this.createTools(context));
    },
  };
}
