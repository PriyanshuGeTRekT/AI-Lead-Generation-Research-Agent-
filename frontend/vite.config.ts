import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// All app API calls use root-relative paths (e.g. /health, /generate-leads).
// In dev we proxy those to the FastAPI backend so the browser sees same-origin
// requests (no CORS config needed). The SSE stream endpoint is proxied too.
const API_TARGET = 'http://localhost:8000'

const proxied = [
  '/health',
  '/leads',
  '/generate-leads',
  '/pipeline-status',
  '/ingest-knowledge',
  '/flush-cache',
  '/metrics',
  '/warehouse',
  '/harvest',
  '/llm',
  '/crm',
  '/startups',
  '/signals',
  '/segment',
  '/enrich',
  '/verify',
  '/stream',
  '/flywheel',
  '/simulate',
  '/config',
  '/chat',
  '/cache',
  '/debug',
  '/track',
  '/visitors',
  '/docs',
  '/openapi.json',
]

const proxy = proxied.reduce<Record<string, { target: string; changeOrigin: boolean }>>(
  (acc, p) => {
    acc[p] = { target: API_TARGET, changeOrigin: true }
    return acc
  },
  {},
)

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  build: { outDir: 'dist', sourcemap: false },
})
