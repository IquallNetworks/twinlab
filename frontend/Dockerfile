# syntax=docker/dockerfile:1

# Multi-stage: `prod` (compose's default target) builds the static bundle and
# serves it through nginx; `dev` is the bind-mount + HMR image that
# compose.dev.yaml swaps in for daily work.

FROM node:22-slim AS base

# pnpm is provisioned by corepack, pinned via package.json's packageManager field.
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# Dev server: compose.dev.yaml bind-mounts the source over /app and ./docs at
# /docs (the guide symlink's target), then Vite serves with hot reload and the
# /api/v1 proxy (vite.config.ts).
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["pnpm", "dev"]

# Build the production bundle. src/content/guide is a symlink to
# ../../../docs/guide — OUTSIDE this Dockerfile's context — so the guide
# markdown comes in through the `docs` additional build context (compose
# supplies it; a bare `docker build` needs --build-context docs=../docs, and
# fails loudly on the COPY without it). The `test` guards the other failure
# mode: a docs context that no longer contains the guide would otherwise
# build an app whose glob import silently matched nothing.
FROM base AS build
COPY . .
COPY --from=docs guide/ /docs/guide/
RUN test -f src/content/guide/README.md && pnpm build

# Production: nginx (BSD-2-Clause) serves the bundle and proxies /api/v1 to
# the backend — HTTP, WebSocket (the node terminal) and SSE (the event
# stream) alike. nginx.conf carries the routing details.
FROM nginx:1.29-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
