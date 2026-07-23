# syntax=docker/dockerfile:1

# Dev-oriented image: compose bind-mounts the source over /app and runs the Vite
# dev server (with the /api/v1 proxy) for hot reload. A production build would be
# a separate multi-stage target serving the static bundle.
FROM node:22-slim

# pnpm is provisioned by corepack, pinned via package.json's packageManager field.
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .

EXPOSE 5173
CMD ["pnpm", "dev"]
