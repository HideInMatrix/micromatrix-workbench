# MicroMatrix Pi MCP Agent

TypeScript 7 / Vite 8 foundation for a local MCP execution service powered by
Pi tools and extensions.

## Architecture

- The web AI model is the **brain** and MCP client.
- Pi tools/extensions are the local execution **body**.
- The MCP server exposes plugin-owned tools at `/mcp`.
- Network-provider plugins expose the local HTTP service through a tunnel.
- The Vite application is a small local control surface, not another agent.

The runtime deliberately does not start a local LLM loop. This avoids two
competing brains and keeps model selection in the web product.

## Versions

- Node.js `>=22.19`
- TypeScript `7.0.2`
- Vite `8.3.1`
- Pi `0.87.1`
- MCP TypeScript SDK `1.30.1`

## Development

```bash
cp .env.example .env.local
npm install --ignore-scripts
npm run check
npm run dev
```
