# Twinlab frontend

A small React UI for the current backend scope: authentication, user management,
and lab management. It talks to the backend over `/api/v1`, which the Vite dev
server proxies (`VITE_PROXY_TARGET`, default `http://localhost:8000`).

## Stack

- **React 19 + TypeScript + Vite.**
- **shadcn/ui** (radix base, `nova` preset) on **Tailwind CSS v4** — always prefer
  a shadcn component (`src/components/ui/*`) over a hand-rolled one.
- **TanStack Query** for server state, **TanStack Router** (code-based) for
  routing, **TanStack Form** for forms.
- **zod** for form and API-response validation.

## Layout

- `src/lib/api.ts` — typed, same-origin fetch client. The httpOnly session cookie
  rides the proxy, so there is no token to store. Responses are zod-parsed
  (`src/lib/schemas.ts`); failures throw `ApiError` (carries HTTP status).
- `src/lib/queries.ts` — TanStack Query options (`me`, `users`, `labs`, `lab`).
- `src/router.tsx` — routes + router. A pathless auth layout resolves `me` in
  `beforeLoad` and redirects to `/login` on 401; `/login` sits outside it.
- `src/components/app-shell.tsx` — nav + current user + sign-out (Users hidden
  without `user:manage`).
- `src/pages/*` — `login`, `users`, `labs`, `lab-detail`. Destructive/mutating
  actions are gated on the caller's permissions (the backend enforces them too).

## Develop

```bash
pnpm install
pnpm dev          # http://localhost:5173
pnpm typecheck    # tsc -b --noEmit
pnpm build        # tsc -b && vite build
```

Adding a shadcn component: `pnpm dlx shadcn@latest add <name>`.
