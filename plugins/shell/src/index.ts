import { createBashTool } from "@earendil-works/pi-coding-agent";
import { registerAgentTools } from "@micromatrix/pi-body";
import type { BodyPlugin } from "@micromatrix/plugin-kit";

export function createShellPlugin(): BodyPlugin {
  return {
    id: "shell",
    displayName: "Pi shell tool",
    createTools: ({ workspace }) => [createBashTool(workspace)],
    installPiExtension(pi, context) {
      registerAgentTools(pi, this.createTools(context));
    },
  };
}
