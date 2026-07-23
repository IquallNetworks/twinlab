import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api/v1 to the backend. The target is configurable so
// the same config works when run directly (localhost default) and under compose
// (VITE_PROXY_TARGET=http://backend:8000, reaching the backend over service DNS).
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

// Port the dev server listens on. 5173 is Vite's conventional default and every
// caller is fine with it; override via FRONTEND_PORT to serve elsewhere. `|| `
// (not `??`) so an empty-string env var also falls back.
const port = Number.parseInt(process.env.FRONTEND_PORT || '5173', 10)

// Public URL the app is served from. Its host is added to the dev server's
// allowed hosts so a non-localhost deployment domain isn't rejected (Vite blocks
// unknown Host headers by default). Unset → Vite's localhost defaults apply.
const deploymentUrl = process.env.DEPLOYMENT_URL
const allowedHosts = deploymentUrl ? [new URL(deploymentUrl).hostname] : undefined

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true, // listen on 0.0.0.0 so the port is reachable from outside the container
    port,
    allowedHosts,
    proxy: {
      // `ws: true` so the WebSocket upgrade for the node terminal
      // (/api/v1/labs/.../terminal) is proxied too, not just HTTP requests.
      '/api/v1': { target: proxyTarget, changeOrigin: true, ws: true },
    },
  },
})
