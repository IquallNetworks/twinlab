// Deployment base path, injected by Vite from the build-time `base` setting
// (vite.config.ts, compose build arg FRONTEND_BASE_PATH): '' when the app is
// served at the origin root, '/twinlab' when it lives under a subpath behind
// a fronting proxy. Everything that constructs a URL outside the router —
// fetch, EventSource, WebSocket — must go through these; router links are
// covered by the router's own `basepath`.
export const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, '')

export const API_BASE = `${BASE_PATH}/api/v1`
