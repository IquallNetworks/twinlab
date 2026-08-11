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

// Deployment base path, for serving the app under a subpath behind a fronting
// proxy (compose build arg FRONTEND_BASE_PATH): '' at the root (the default),
// or '/twinlab'-shaped — leading slash, no trailing slash. Baked into the
// bundle (asset URLs, router basepath, API/SSE/WS paths via
// src/lib/base-path.ts) and into the image's nginx config, so it is a
// build-time choice. Validated here because a malformed value would otherwise
// surface as a blank page with 404 assets.
const basePath = process.env.BASE_PATH ?? ''
if (basePath !== '' && !/^\/[A-Za-z0-9._~-]+(\/[A-Za-z0-9._~-]+)*$/.test(basePath)) {
  throw new Error(
    `BASE_PATH must be empty or like "/twinlab" (leading slash, no trailing slash); got ${JSON.stringify(basePath)}`,
  )
}

export default defineConfig({
  base: `${basePath}/`,
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
    fs: {
      // The operator guide is imported from src/content/guide, which is a
      // SYMLINK to the repository's docs/guide. Vite resolves symlinks, so the
      // real path sits outside the project root and the dev server must be
      // told it may read it. Both entries resolve correctly under compose too,
      // where the root is /app and ./docs is mounted at /docs.
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../docs', import.meta.url)),
      ],
    },
    proxy: {
      // `ws: true` so the WebSocket upgrade for the node terminal
      // (/api/v1/labs/.../terminal) is proxied too, not just HTTP requests.
      '/api/v1': { target: proxyTarget, changeOrigin: true, ws: true },
    },
  },
})
