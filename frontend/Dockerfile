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
# Deployment base path: '' serves at the origin root, '/twinlab'-shaped serves
# under a subpath (compose wires FRONTEND_BASE_PATH through). Baked into the
# bundle by Vite (which also validates the shape) and into nginx.conf here:
# SPA_LOCATION falls back to '/' at the root, and ROOT_REDIRECT points a bare
# / at a subpath deployment's real home.
ARG BASE_PATH=""
COPY . .
COPY --from=docs guide/ /docs/guide/
RUN test -f src/content/guide/README.md \
 && BASE_PATH="$BASE_PATH" pnpm build \
 && SPA_LOCATION="${BASE_PATH:-/}" \
 && ROOT_REDIRECT="" \
 && if [ -n "$BASE_PATH" ]; then ROOT_REDIRECT="location = / { return 302 $BASE_PATH/; }"; fi \
 && sed -e "s|\${BASE_PATH}|$BASE_PATH|g" \
        -e "s|\${SPA_LOCATION}|$SPA_LOCATION|g" \
        -e "s|\${ROOT_REDIRECT}|$ROOT_REDIRECT|g" nginx.conf > nginx.rendered.conf

# Production: nginx (BSD-2-Clause) serves the bundle and proxies /api/v1 to
# the backend — HTTP, WebSocket (the node terminal) and SSE (the event
# stream) alike. nginx.conf carries the routing details.
FROM nginx:1.29-alpine AS prod
ARG BASE_PATH=""
COPY --from=build /app/nginx.rendered.conf /etc/nginx/conf.d/default.conf
# At the root this is html/ exactly as before; a subpath build nests the
# bundle so URL paths map onto the filesystem with no aliasing.
COPY --from=build /app/dist /usr/share/nginx/html${BASE_PATH}
EXPOSE 5173
