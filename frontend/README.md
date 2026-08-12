# Twinlab frontend

The web UI over the Twinlab API: a role-aware dashboard, routed lab tabs, a guided visual topology
builder with a full-syntax text escape hatch, live topology and link views, a jobs center, per-node
connect/logs/terminal surfaces, config import, the template library, and the auth/RBAC and account
screens.

It talks to the backend over `/api/v1`, proxied by whichever of the two serving modes is running.
The compose default is the **production build**: a multi-stage image (`Dockerfile` target `prod`)
that compiles the bundle and serves it through nginx, whose `nginx.conf` owns the `/api/v1` proxy
(WebSocket terminal and SSE stream included). Development uses the **Vite dev server** instead —
`docker compose -f compose.yaml -f compose.dev.yaml up -d --build` — with hot reload over
bind-mounted source and the proxy from `vite.config.ts` (`VITE_PROXY_TARGET`, default
`http://localhost:8000`). Either way the session cookie is httpOnly and rides that same-origin
proxy, so there is no token to store.

The production build can serve under a subpath for a fronting proxy (`FRONTEND_BASE_PATH=/twinlab`
in `.env`): Vite bakes the base into asset URLs, `src/lib/base-path.ts` derives the router
`basepath` and the API/SSE/WebSocket prefixes from it, and the image's nginx config is rendered
with every location moved under the base — so the container serves `/twinlab/…` natively and the
proxy strips nothing. The dev server always runs at the root.

The operator guide is compiled into the bundle from `docs/guide/` through the `src/content/guide`
symlink. That target sits outside the docker build context, so the production build stage pulls it
in via the `docs` additional build context (compose supplies it; a bare `docker build` needs
`--build-context docs=../docs`).

## Stack

- **React 19 + TypeScript + Vite** (pnpm).
- **shadcn/ui** (radix base) on **Tailwind CSS v4** — always prefer a shadcn component
  (`src/components/ui/*`) over a hand-rolled one. Add with `pnpm dlx shadcn@latest add <name>`.
- **TanStack Query** for server state, **TanStack Router** (code-based) for routing, **TanStack
  Form** for forms, **zod** for form and response validation.
- **React Flow** + **dagre** for the topology and builder canvases, **CodeMirror 6** for every
  YAML/JSON/Jinja surface, **xterm** for the node terminal, **cmdk** for the command palette,
  **sonner** for toasts, **react-markdown** + **remark-gfm** for the operator guide at `/docs`.

## Layout

| Path | What it is |
| --- | --- |
| `src/lib/api.ts` | The typed, same-origin client. Responses are zod-parsed (`schemas.ts`); any non-2xx raises `ApiError` carrying the backend's `{code, message, extras}` envelope. |
| `src/lib/queries.ts` | TanStack Query options. Query keys are rooted (`['labs']`, `['jobs']`, `['templates']`) so one invalidation refreshes a whole family. |
| `src/lib/use-lab-events.ts` | The SSE subscription: records events to the activity store and invalidates the `['labs']` / `['jobs']` roots. |
| `src/router.tsx` | Routes. A pathless auth layout resolves `me` in `beforeLoad` and redirects to `/login` on 401; `/login` sits outside it. |
| `src/pages/` | `dashboard`, `labs`, `lab-import`, `jobs`, `users`, `groups`, `account`, `login`, `docs` (the operator guide, outside the auth gate — `src/content/guide` is a symlink into `../docs/guide`), and `lab/` — the lab detail layout route with its overview / build / nodes / operations / access children. |
| `src/components/lab/build/` | The builder: canvas, palette, inspector, the shared searchable `device-picker.tsx`, and `build-state.ts` — the reducer that owns the document, plus the `historyReducer` wrapping it for undo/redo. |
| `src/components/lab/topology/` | The read-only canvas: node/LAN/stub renderers, dagre layout, PNG export. |
| `src/lib/build-doc.ts` | **The parser/emitter** — netlab YAML ⇄ a typed core plus lossless `extras` passthrough. Pure, dependency-light, and the round-trip invariant `parse(emit(doc)) == doc` is load-bearing. |
| `src/lib/topology.ts` | Best-effort parse of netlab's link forms for the read-only canvas. Unresolvable entries surface in a strip, never silently dropped. |
| `src/styles/theme.css` | Schematic, the design system, as one CSS token pack at `:root`/`.dark` — shadcn's full set plus Twinlab's `--id-*` extras (fonts, canvas motif, header chrome, code-editor syntax). Light/dark is the only visual choice offered. |

Actions are gated on the caller's permissions (the backend enforces them independently — the UI
gate is about not offering what would fail).

## Develop

```bash
pnpm install
pnpm dev             # http://localhost:5173
pnpm typecheck       # tsc -b --noEmit
pnpm build           # tsc -b && vite build
pnpm test            # vitest — src/**/*.test.{ts,tsx,mjs}
pnpm check:build-doc # parser/emitter invariants
```

All four checks are gates (the two `check:*` scripts are now aliases scoping `pnpm test` to one
file). `pnpm test` is **vitest** (2026-08-12): pure modules run under node, component tests opt
into jsdom with a `// @vitest-environment jsdom` docblock and drive real renders through
`@testing-library/react` — which is where behaviour that used to be verifiable only through a
live stack and the e2e suite belongs now (the colour-grammar assertions in
`status-badge.test.tsx` are the worked example). The old hand-rolled check runners
(`scripts/*.mjs`, which bundled the pure modules with vite's JS API to run under plain node)
are gone — both ported verbatim: `src/lib/build-doc.test.mjs` (90 round-trip, gate and
emit-blocker cases against `build-doc.ts`, all three `examples/` definitions included) and
`src/lib/test-suite-model.test.mjs` (48 checks over the suite model, fact completions and the
results module). Kept `.mjs` on purpose: gate checks deliberately feed the parsers malformed
input, which typed test code would cast around line-by-line for no added truth.

The browser layer's end-to-end coverage lives in `../e2e` (Playwright, against its own stack).
Nothing there uses `data-testid` — specs locate by role and label, so keep `<Label htmlFor>`
pairings and `aria-label`s intact.
