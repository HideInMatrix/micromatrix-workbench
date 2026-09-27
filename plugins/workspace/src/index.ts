import {
  createEditTool,
  createFindTool,
  createGrepTool,
  createLsTool,
  createReadTool,
  createWriteTool,
} from "@earendil-works/pi-coding-agent";
import { registerAgentTools } from "@micromatrix/pi-body";
import type { BodyPlugin } from "@micromatrix/plugin-kit";

export function createWorkspacePlugin(): BodyPlugin {
  return {
    id: "workspace",
    displayName: "Pi workspace tools",
    createTools: ({ workspace }) => [
      createReadTool(workspace),
      createGrepTool(workspace),
      createFindTool(workspace),
      createLsTool(workspace),
      createEditTool(workspace),
      createWriteTool(workspace),
    ],
    installPiExtension(pi, context) {
      registerAgentTools(pi, this.createTools(context));
    },
  };
}
