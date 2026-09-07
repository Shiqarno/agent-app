/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Vite runs inside the `frontend` container and is reached via the
    // host's published port (5173:5173), so it must listen on the
    // container's external interface, not just loopback -- otherwise the
    // host can't connect at all ("connection refused"), regardless of the
    // `--host` CLI flag in package.json's dev script.
    host: '0.0.0.0',
    // Proxies same-origin /api/* requests to the backend container (Docker
    // Compose service name, resolved on the compose network) so the
    // browser sees the Web UI and the API as a single origin -- otherwise
    // Chrome drops the SameSite=Lax session cookie on a cross-origin
    // localhost:5173 -> localhost:8000 request.
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
