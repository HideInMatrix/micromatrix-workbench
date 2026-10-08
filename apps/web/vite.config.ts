import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { webDependencyNotices } from '../../scripts/dependency-notices.mjs'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root: rootDir,
  base: './',
  plugins: [
    // Keep VDOM mode on Vue 3.5. Components are intentionally written in a
    // Vapor-compatible style so this can be switched after Vue 3.6 stable.
    vue(),
    webDependencyNotices(path.resolve(rootDir, '../..')),
    UnoCSS({ configFile: path.resolve(rootDir, 'uno.config.ts') }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
