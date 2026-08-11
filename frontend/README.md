# Twinlab frontend

The web UI over the Twinlab API: a role-aware dashboard, routed lab tabs, a guided visual topology
builder with a full-syntax text escape hatch, live topology and link views, a jobs center, per-node
connect/logs/terminal surfaces, config import, the template library, and the auth/RBAC and account
screens.

It talks to the backend over `/api/v1`, which the Vite dev server proxies (`VITE_PROXY_TARGET`,
default `http://localhost:8000`). The session cookie is httpOnly and rides that proxy, so there is
no token to store.

## Stack

- **React 19 + TypeScript + Vite** (pnpm).
- **shadcn/ui** (radix base) on **Tailwind CSS v4** — always prefer a shadcn component
  (`src/components/ui/*`) over a hand-rolled one. Add with `pnpm dlx shadcn@latest add <name>`.
- **TanStack Query** for server state, **TanStack Router** (code-based) for routing, **TanStack
  Form** for forms, **zod** for form and response validation.
- **React Flow** + **dagre** for the topology and builder canvases, **CodeMirror 6** for every
  YAML/JSON/Jinja surface, **xterm** for the node terminal, **cmdk** for the command palette,
  **sonner** for toasts.

## Layout

| Path | What it is |
| --- | --- |
| `src/lib/api.ts` | The typed, same-origin client. Responses are zod-parsed (`schemas.ts`); any non-2xx raises `ApiError` carrying the backend's `{code, message, extras}` envelope. |
| `src/lib/queries.ts` | TanStack Query options. Query keys are rooted (`['labs']`, `['jobs']`, `['templates']`) so one invalidation refreshes a whole family. |
| `src/lib/use-lab-events.ts` | The SSE subscription: records events to the activity store and invalidates the `['labs']` / `['jobs']` roots. |
| `src/router.tsx` | Routes. A pathless auth layout resolves `me` in `beforeLoad` and redirects to `/login` on 401; `/login` sits outside it. |
| `src/pages/` | `dashboard`, `labs`, `lab-import`, `jobs`, `users`, `groups`, `account`, `login`, and `lab/` — the lab detail layout route with its overview / build / nodes / operations / access children. |
| `src/components/lab/build/` | The builder: canvas, palette, inspector, and `build-state.ts`, the reducer that owns the document. |
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
pnpm check:build-doc # parser/emitter invariants
```

All three checks are gates. `check:build-doc` runs 90 round-trip, gate and emit-blocker cases
against `build-doc.ts` — including all three `examples/` definitions — by bundling the pure module
with vite's own API and running it under plain node. **The frontend has no test runner**, so this
is its only regression net; changes to the parser or emitter belong with a case there.

The browser layer's end-to-end coverage lives in `../e2e` (Playwright, against its own stack).
Nothing there uses `data-testid` — specs locate by role and label, so keep `<Label htmlFor>`
pairings and `aria-label`s intact.
