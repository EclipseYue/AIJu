import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL('../dist', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          cytoscape: ['cytoscape'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
})
