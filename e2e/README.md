# Twinlab e2e — the Playwright UX suite

Drives the real frontend in a real browser against a **dedicated, pristine stack** — the
browser-layer complement to `../blackbox` (which proves the API contract through the client).
It covers what blackbox cannot: login/auth flows, role-gated affordances actually hidden or
shown, the dashboard → builder → deploy → operate journeys, dialogs, toasts, empty states and
canvas interactions — asserting on **exact dynamic text** throughout.

## The e2e stack

The suite owns a parallel compose project, **`twinlab-e2e`**, that runs beside the dev stack on
the same Docker daemon (the `twinlab-nokia` pattern): its own volumes, database, mgmt-subnet
pool and ports, so nothing here touches dev data.

| What | Value |
| --- | --- |
| Compose project | `twinlab-e2e` (`stack.env` + `compose.e2e.yaml` over the root `compose.yaml`) |
| Frontend | `http://localhost:5373` |
| SSH jump | port `2422` |
| clab-api / hostprep | host ports `8290` / `8291` |
| Mgmt subnet pool | `10.79.0.0/16` |
| Lab files | `/var/lib/twinlab-e2e/lab-files` |

`stack.env` carries test-only values (including the bootstrap admin credentials the suite logs
in with) and is checked in on purpose. The two host-coupled secrets that cannot be test-only —
`CLAB_API_USERNAME` / `CLAB_API_PASSWORD`, a real host PAM user in the `clab_api` group — are
inherited from the repo-root `.env`, which must exist.

**Every run starts from an empty backend**: the Playwright global setup runs
`scripts/stack.sh reset` — leftover `clab-e2e*` lab containers are swept, the stack goes down
with its volumes, the lab-files dir is cleared, and the stack comes back up. The backend
entrypoint re-runs migrations, re-seeds RBAC and re-creates the bootstrap admin, so the suite
always opens on one admin user and zero labs.

## One-time host setup

```sh
# The host-shared lab-files dir (same-path invariant, like the dev stack's):
sudo mkdir -p /var/lib/twinlab-e2e/lab-files

# Node images the journey deploys. VyOS is pinned by digest + local tag (the
# registry only publishes a rolling :latest) — the tag must match the catalog's
# pin (see the root README's "Up" section):
docker pull ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50
docker tag ghcr.io/sysoleg/vyos-container@sha256:dc8d4233b2b7e9e94d96fd8d10a40a6b256c5d1aec1c960e02cdf835ca68fe50 \
  twinlab/vyos:2026.05.30-0046-rolling
docker pull quay.io/frrouting/frr:10.6.1
docker pull python:3.13-alpine

# Suite dependencies + browser:
pnpm install
pnpm exec playwright install chromium
```

The repo-root `.env` must define `CLAB_API_USERNAME` / `CLAB_API_PASSWORD` (it already does for
the dev stack).

## Running

```sh
pnpm test                 # full run: reset stack → setup → fast → journey (~7–8 min warm)
pnpm test:fast            # setup + the fast tier only (no containers deployed)
pnpm test:journey         # runs its dependencies too; add --no-deps to skip the fast tier
pnpm report               # open the HTML report of the last run
pnpm typecheck
```

Projects: **`setup`** (the login spec — saves the admin `storageState`), **`fast`** (auth,
empty states, users/groups, lab authoring, builder, templates, import, account, role gating,
command palette — never deploys a container), **`journey`** (creates, deploys and operates the
`e2e-net` topology end to end: nodes, terminal, links, netem, validation, drift, teardown).
One worker, ordered spec files — the suite is a story, not a grid.

### The iteration loop

A full run measures ~7.5 min of wall clock with a warm image cache (2026-08-12: 85s
reset+overhead, 3.5m fast, 2.5m journey — 67 specs) and meaningfully more when the frontend
build layer is cold, since any source edit invalidates it. Right for the gate before a push,
wrong for every edit in between. In between:

```sh
# Bring the stack up with the Vite dev server instead of the static build:
# frontend edits hot-reload into the running stack, no image rebuild ever.
scripts/stack.sh reset dev        # or `up dev` if the stack state is fine as-is

# Iterate at the tier level (E2E_CLEAN empties the running stack through the
# API in seconds — labs, users, groups, templates, keys):
E2E_CLEAN=1 pnpm test:fast                        # the whole no-container tier
E2E_CLEAN=1 pnpm test:journey -- --no-deps        # only when deploy/ops paths changed

# A SINGLE spec file pairs with E2E_SKIP_RESET, not E2E_CLEAN: the tiers are
# ordered stories (13-tests-tab edits the lab 04/05 built), so one file only
# works on top of the state a previous run left behind. Same for re-running
# exactly what failed after a fix:
E2E_SKIP_RESET=1 pnpm exec playwright test tests/fast/13-tests-tab.spec.ts --project=fast
E2E_SKIP_RESET=1 pnpm exec playwright test --last-failed

# The gate, once, before pushing — prod build, pristine stack, everything:
pnpm test
```

`E2E_CLEAN` is honest about what it is: empty enough for the loop, not pristine (sessions and
id sequences survive, and it needs the stack already up). The specs that assert a virgin
stack, and the prod nginx frontend the users actually get, are what the final `pnpm test`
still exists for. Same idea elsewhere: backend iteration runs the touched pytest files and
blackbox with `-m "not deploy"`, with the full suites at the same pre-push gate.

### Watching a run over SSH (UI mode)

There is no display on a remote box, so `--headed` cannot work. UI mode serves itself over
HTTP instead — forward the port and drive it from your own browser:

```sh
# on the host (skip the reset when the stack is already up and healthy)
E2E_SKIP_RESET=1 pnpm exec playwright test --ui-host=127.0.0.1 --ui-port=9323
# from your machine
ssh -L 9323:localhost:9323 <host>          # then open http://localhost:9323
```

Bind 127.0.0.1, not 0.0.0.0 — the tunnel terminates on the remote's loopback, so there is no
reason to publish the UI on every interface.

**Two things that look like breakage and are not:**

1. **Only `auth.setup.ts` is listed.** UI mode's project filter defaults to the FIRST project
   in the config array, which is `setup`. Expand the filter panel (the chevron beside the
   filter box, or click the `Status: … Projects: …` summary) and tick **fast**. The choice is
   stored per browser and survives a reload. `--project=fast` on the command line does NOT
   move the UI filter — it only scopes what a run executes.
2. **A long pause before anything appears.** Starting UI mode runs `globalSetup`, i.e. the
   whole `stack.sh reset` — `down -v`, an image rebuild, and a fresh `up`. That is minutes,
   and the tree stays sparse until it finishes. `E2E_SKIP_RESET=1` skips it when the stack is
   already running.

Because UI mode resets ONCE at startup and then re-runs on demand, `fast/11-builder-l3vpn`
clears its own lab first, so it can be replayed as many times as you like in one session.

## Conventions

- **Assert exact strings** — statuses, badges, toasts, counts, summary lines, empty-state and
  dialog copy. The point is to catch unseen text-level regressions.
- **Never `waitForLoadState('networkidle')`** — the app holds an SSE connection open for the
  whole session; it never settles.
- Accessibility-first locators (`getByLabel`, `getByRole`, exact `getByText`); shadcn
  `data-slot` attributes for structure. The app has no `data-testid` and the suite adds none.
- Radix widgets need driving helpers (`lib/radix.ts`): `Select` is not a native `<select>`,
  `Checkbox` state is `data-state`. Dialogs/menus render into body portals.
- Every YAML/JSON/Jinja surface is CodeMirror — type through `lib/editor.ts`, never `fill()`.
- Clipboard effects are asserted through their toasts ("Copied address"), not clipboard reads.
- Lab/user/group names created by the suite are `e2e-` prefixed — that prefix is what the
  stack reset's container sweep keys on.
