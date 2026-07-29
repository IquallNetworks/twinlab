# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## What Twinlab Is

Twinlab generates reproducible simulated network topologies from a declarative definition. It is a
layer on top of [Containerlab](https://containerlab.dev/) — driven through
[netlab](https://netlab.tools/) — that lets engineers describe network nodes, links, services, and
test scenarios declaratively, then deploys reproducible lab environments from that definition. Its
purpose is digital-twin and network-automation testing: validating configurations, orchestration
workflows, service provisioning, and operational procedures in a safe sandbox before applying them
to production networks.

The declarative input is a netlab definition — netlab syntax (`provider`, `defaults.device`,
`module`, `nodes`, `links`). A worked example lives at `examples/mpls-l3vpn.yml` (a VyOS MPLS
L3VPN core: OSPF + LDP + MP-BGP VPNv4). The lab's name is not taken from the definition — it is
the lab's durable identity, chosen at create (`CreateLabRequest.name`).

**Twinlab is fully open source.** Everything we distribute must be open source too: every
dependency, bundled tool, and reference platform we ship or require must carry an OSI-approved
license compatible with Twinlab's own (Apache 2.0). Before adding a dependency or leaning on an
external tool, confirm its license clears this bar — a non-open-source or incompatibly-licensed
component is a blocker to raise, not a choice to make quietly.

**Target platform is Linux; do not design for anything else.** Twinlab's lab layer is host-coupled
to Linux by nature (containerlab drives Linux kernel networking directly). The development target is
Linux, full stop — write code, choose dependencies, and make design decisions for Linux only, never
trading anything off for another platform. Running on Apple Silicon / macOS is a *speculative,
below-secondary* idea parked in `docs/dev-on-apple-silicon.md` for possible later exploration; it is
**not a goal and must never influence a decision here**. If the project never supports it, that is
completely fine — that is precisely why it was deferred. Do not add macOS/arm64 accommodations,
caveats, or abstractions on its behalf unless and until it is explicitly picked up as real work.

## Current State

The **API v1.0 contract** lives at `docs/twinlab_client_shape.py` — a reviewed contract sketch the
backend now implements in full (twelve deltas; delta 12 is the async job model). Two non-compose
projects sit beside the services: **`client/`** (`twinlab-client`, the distributable async Python
client — PyPI-ready, published at v1.0) and **`blackbox/`** (the black-box test suite: 88 tests
exercising a live stack through the client only; all green, README documents env config and the
`deploy` marker). The suite is the contract's enforcement — backend changes are verified against
it, and contract changes go through review.

The project is a `docker compose` stack (`compose.yaml`, project name `twinlab`) of five services:

- **`frontend/`** — Vite + React + TypeScript (pnpm). **Currently targets the PRE-rework wire and
  is partially broken against the v1.0 backend** (accepted: no end users; its own rework to the
  v1.0 contract is the next step). Its dev server proxies `/api/v1` to the
  backend (`VITE_PROXY_TARGET`, default `http://localhost:8000`). UI stack: **shadcn/ui** (radix
  base) on Tailwind v4, the **TanStack** family (Query for data, Router in code-based mode for
  routing, Form for forms) and **zod** for validation. It covers the current backend scope —
  cookie-session **login**, **user management** (`/users`: list, create, edit roles), and **lab
  management** (`/labs` list + deploy dialog, `/labs/$name` detail: a control panel with
  edit-definition/redeploy/configure/destroy, whole-lab and per-node start/stop/restart, save-config,
  per-node logs, a live interface inventory, per-node netem link impairment (set/show/reset
  delay/jitter/loss/rate/corruption), a per-node **web console** (an xterm.js terminal over a
  WebSocket to the node, ssh/shell, shown only while the node is up), and a **test-suites** panel
  (view suites grouped config-time-first, run one on demand, expand per-test pass/fail/error, author
  the suite set as JSON; a "config-time failed" badge when the last gate failed) — controls in
  focused `components/lab/*` components).
  Auth gate: a pathless layout route resolves `GET /auth/me` in `beforeLoad` and redirects to `/login`
  on 401; action buttons are gated on the caller's permissions. Live updates: `useLabEvents`
  (mounted in `AppShell`) subscribes to the `/events` SSE stream and invalidates the `['labs']`
  query tree on each event, so lab state refreshes without polling. API access goes through a typed,
  zod-parsed fetch client (`src/lib/api.ts`). Gates: `pnpm typecheck` + `pnpm build`.
- **`backend/`** — FastAPI (uv, **Python 3.14**, ids are stdlib **UUIDv7**). Turns a declarative
  netlab definition into a running lab: runs `netlab create` to generate a containerlab topology,
  then deploys it through the clab-api server (piped inline as `topologyContent`). Config push is
  delegated to the netlab-runner. **Every non-2xx wears one error envelope** `{code, message,
  extras}` (`api_errors.py`: ApiError + handlers covering FastAPI validation and framework errors;
  stable code slugs like `lab_not_found`, `permission_denied`, `netlab_invalid`). **Lab lifecycle
  is split** (create → author → deploy): `POST /labs {name}` creates a bare record (status
  `created`, no definition) and allocates the lab's management `/24` from `MGMT_SUBNET_POOL` up
  front; `PUT /labs/{name}` authors/replaces the stored definition (validated by a dry `netlab
  create`; the record's name and subnet are re-pinned into it — `set_lab_name`/`set_mgmt_subnet`,
  an explicit `addressing.mgmt.ipv4` wins); `POST /labs/{name}/deploy` is the ONLY deploy verb —
  from the stored definition, fresh or overwrite-in-place, opt-in `configure`; 409 `no_definition`
  on an unauthored record. **The four long operations (deploy/configure/destroy/suite-run) are
  ASYNC JOBS** (contract delta 12): pre-accept checks stay synchronous, then the route returns
  **202 + a running Job** and the work runs in an in-process task; callers poll `GET
  /labs/{name}/jobs/{id}` (+ `GET .../jobs?limit=`, both `lab:read`, readable on a soft-deleted
  lab so a destroy-with-remove job stays pollable; a revived name starts with no history). Jobs
  persist in a `jobs` table; the partial unique index (one `running` row per lab) IS the operation
  mutex — a concurrent submit of ANY kind is 409 `job_in_flight`. Job failed = could-not-run (the
  error envelope on `job.error`); `config_failed`/`validation_failed` stay job successes. Startup/
  shutdown sweeps (`job_store.sweep_orphans`) fail orphaned jobs (`backend_restart`/
  `backend_shutdown`) and restore a lab wedged at `deploying` (single-process assumption). A lab is
  a **durable record** (a `labs` table): definition/suites/templates are reused by deploy and
  configure — the caller never resupplies them — and the record survives destroy (status
  `destroyed`, redeployable, subnet kept). `DELETE /labs/{name}` requires a RUNNING lab (409
  `lab_not_running` at submit, via a fast inspect pre-check — 404 stays existence-hiding);
  `?remove=true` soft-deletes the record and RELEASES its subnet. Config is env-sourced through a
  typed `load_settings(env) -> Result` loader (not pydantic-settings).
  Other endpoints under `/api/v1`: `health`, `health/ready`, `auth/*` (login/logout/me, `PUT
  /auth/password` self-change that keeps the calling session, and **API keys** — `POST/GET/DELETE
  /auth/api-keys`, sha256-stored Bearer secrets shown once, dead when their user is deactivated or
  deleted), `users/*` (list/create/get/roles/password-reset/activate-toggle/delete, with a
  **last-admin guard**: 409 on deactivating or deleting the only active admin), `groups/*`,
  `roles`, `principals`, `GET /labs` + `GET /labs/{name}` (stored record merged with best-effort
  live node state; owner as `Principal {id, name}`, `config_time_status` tri-state, per-lab
  `permissions` MASKED to the lab-scoped set). **Test suites** (Twinlab's own validation, not `netlab
  validate` — see ROADMAP Phase 5): declarative assertions stored on the lab record (never sent to
  `netlab create`), each running a command over clab-api `exec` and matching stdout with a safe
  primitive (contains/not_contains/matches/json_path; no expression eval), polled until they pass or
  a per-test `wait` elapses. `GET/PUT /labs/{name}/test-suites` (read/author), `POST
  /labs/{name}/test-suites/{suite}/run` (run one on demand — an async job like the other long
  operations). A suite's `stage` (`config-time` |
  `runtime`) controls only *automatic* execution: `config-time` suites run at the end of a configure
  (deploy/configure, gated by `skip_config_time_checks` — a skip RETAINS the previous gate) and gate
  "config done" — a failure leaves the lab deployed with `config_time_status="failed"` and returns
  status `validation_failed`, so a failed config is unambiguous. **HTTP errors mean "could not
  run"**: a config push that ran but failed on ≥1 node is a 2xx `status="config_failed"` with
  per-node results. The runner + pure matcher
  live in `services/validation.py`; results persist per-suite in `last_validation`.
  **Runtime control/observability** over live clab-api state (not
  the definition): `POST /labs/{name}/nodes/{node}/{start|stop|restart|pause|unpause}` and
  `POST /labs/{name}/{start|stop|restart}` (power control), `POST /labs/{name}/{pause|unpause}`
  (whole-lab freeze — clab-api has no lab-level pause, so this fans out over the nodes, non-atomic),
  `POST /labs/{name}/save` (persist running config), `GET /labs/{name}/nodes/{node}/logs` (container
  logs, `?tail=`), `GET /labs/{name}/interfaces` (per-node inventory keyed by SHORT node name;
  `?node=` filters by it), and **netem link impairment** keyed by node+interface (`GET/POST
  /labs/{name}/nodes/{node}/netem` — durations are structured `{value, unit}` pairs; set has
  REPLACE semantics: the body is the complete desired impairment, omitted = cleared, empty body =
  clear all; show lists only ACTIVELY impaired interfaces — the node's container is resolved from
  live state, and these routes precede the `{action}` node route so `netem` isn't captured by the
  action path param). Node state carries a docker-vocabulary `state` (unknown upstream values 502
  loudly) and
  the management IP (`mgmt_ip`, from clab's `ipv4_address`) for a copy-paste `ssh` command. A
  **Server-Sent Events** stream at `GET /events` (`lab:read`) relays clab-api's live lab events
  (distilled to `{lab, node, action, timestamp}`), auth resolved up front so the long-lived
  connection doesn't pin a DB session, so the frontend refreshes without polling. A **web terminal**
  WebSocket at `WS /labs/{lab_name}/nodes/{node_name}/terminal?protocol=ssh|shell` (`lab:terminal`)
  proxies clab-api's terminal-session stream: it authorizes off the handshake credentials *before*
  accept and releases the DB session before the relay (same rule as `/events`), creates a clab-api
  terminal session, and relays its JSON frames transparently in both directions (the browser does
  its own base64 decode), deleting the session on close. clab-api's terminal stream is a client
  WebSocket, so it uses the `websockets` library (httpx can't); terminal-sessions accepts the short
  node name, so no container resolution is needed. DB-backed auth + RBAC guard everything — **two
  credentials**: opaque session cookies OR `Authorization: Bearer <api-key>` (shared resolver used
  by HTTP routes, `/events`, and the terminal handshake). Scoped RBAC (`docs/rbac-v2.md` + the
  contract's catalog appendix): `lab:read` for reads/events/netem-show/suite-read, `lab:edit` for
  edit/deploy/suite-and-template-author, `lab:configure` for configure/power/save/netem-set (the
  automatic config-time run rides it), `lab:validate` for on-demand suite runs, `lab:terminal`,
  `lab:destroy`, `lab:grant`; global-only `lab:create`, `user:manage`, `group:manage`. The clab-api
  client (`services/clab_api.py`) routes every authenticated call through one `_authed` helper.
  Errors-as-values throughout; `try`/`except` only at the subprocess/httpx/pydantic boundaries.
- **`netlab-runner/`** — FastAPI (uv) config-push sidecar. `POST /configure {definition}` runs
  `netlab create` (regenerate the inventory) then `netlab initial`, which drives Ansible over the
  `docker` connection (exec into `clab-<lab>-<node>` by name via the mounted Docker socket — no host
  network, no SSH). Returns structured per-node results (parsed from Ansible's PLAY RECAP). netlab
  (MIT) is aggregated with ansible-core + community.docker (GPLv3) as separate processes.
- **`clab-api`** — the containerlab API server (`srl-labs/clab-api-server`, Apache-2.0), host-coupled
  (host network + PID, Docker socket and PAM databases mounted); it deploys lab nodes as sibling
  containers on the host daemon and authenticates a host user in the `clab_api` group.
- **`postgres`** — backs the RBAC store (users, roles, permissions, sessions) and the durable lab
  records (`labs`: definition + status + owner) via SQLAlchemy async + Alembic; migrations run in the
  backend entrypoint.

Also present: `LICENSE` (Apache 2.0). Backend + netlab-runner quality gates: `ruff format` + `ruff
check`, basedpyright (strict), pytest.

**End-to-end deploy + config push is proven:** create → `PUT` the definition → `POST
/labs/{name}/deploy` with `configure: true` (202 + job) → poll the job to `succeeded` → nodes
deployed *and* configured via clab-api deploy + the netlab-runner, config-time gate green —
exercised continuously by the black-box suite's `deploy`-marked tests (linux nodes) and verified
on VyOS (OSPF adjacency reaches Full) and cisco IOL. Needs a host user in the `clab_api` group,
node images pulled, and clab-api running. Keep this section current as the project evolves.

A previous, complete iteration lives in the sibling directory **`../bak.0`** (a four-layer Python
package with an HTTP backend / CLI client / privileged lab-runner split, plus a full `docs/` design
set and ADRs). Treat it as **reference / prior art**, not as a spec to reproduce: consult it for how
a problem was solved before, but only carry something over when it's asked for or clearly still
applies. The new structure is decided here, in this tree.

## Domain facts that must hold (they cost real debugging to relearn)

- **netlab generates and configures, but does not deploy.** Use `netlab create` to generate the
  Containerlab topology (deploy is clab-api's job, separately), and `netlab initial` to push device
  config (in the netlab-runner, over Ansible's `docker` connection). **Never `netlab up`** — it
  `sudo`s and couples deploy + config in one opaque step, breaking the reproducibility seam and the
  clab-api deploy boundary. (History: config push was briefly hand-rolled per-device — VyOS
  ConfigSession over the clab-api exec channel — then replaced by netlab because hand-rolling doesn't
  scale across OSes and can't honor netlab's best-effort lines; `netlab initial` itself is
  deterministic, so it does *not* break reproducibility the way `netlab up` does.)
- **Declarative and reproducible is the whole point.** The definition is the sole source of truth
  for a lab; the same definition must always produce the same environment.
- **A node's `device` is intentful, not universal.** Don't quietly default it (e.g. to `vyos`) —
  the definition must state it.

## Working conventions

These are the developer's standing preferences; they carry across sessions regardless of how the
code is structured.

### Version control
- **Commit proactively in small, logical units** — each a self-contained change whose message says
  *what* and *why*. Err toward more commits, not fewer (we squash before merging).
- **Never push** and never `--no-verify` unless explicitly asked. Pushing/merging is the
  maintainer's call.
- **No authorship trailers** — do not add `Co-Authored-By`, `Generated with`, or any attribution to
  commit messages or PR bodies. Keep messages to the change itself.

### Code quality (once the toolchain is scaffolded)
- Expect a strict Python setup managed with **`uv`**: `ruff format` + `ruff check` (strict),
  **basedpyright** in strict mode (warnings are errors), and **pytest**. "Done" means all gates are
  green.
- **Suppressions and weakened checks require approval.** Don't add `# type: ignore`, `# noqa`,
  per-file ignores, rule exclusions, or severity downgrades without surfacing *what*, *where*, and
  *why it's unavoidable* first. Once approved, scope it as narrowly as possible.
- **Ask before adding a dependency.** Don't reimplement what a maintained library does well, but get
  approval, then add with `uv add <name>` and let uv resolve the version — never hand-pin. Confirm
  the license is open source and Apache-2.0-compatible before proposing it (see above).

### Style
- **Errors as values, not exceptions.** Prefer returning a typed result (success-or-typed-error)
  over raising. `try`/`except` belongs only in thin boundary adapters that translate an unavoidable
  third-party exception (Pydantic, `subprocess`, file I/O) into a typed result — never as control
  flow in our own code.
- **Be spare with defaults and fallbacks.** A default is legitimate only when *every* caller is okay
  with it; otherwise make the field required. Document every surviving default with *why this value*
  next to it. Apply the same scrutiny to `x or <fallback>` / `.get(k, <fallback>)` — a fallback that
  papers over a missing value is a bug hiding place; surface it as a typed error instead.
- **Typing carries intent; docstrings are sparing.** Comment to explain what the code can't say —
  *why this value*, a non-obvious invariant, a domain fact — not to restate a type or narrate a
  change. Pass dependencies explicitly; keep side effects at the edges; keep modules small.

### Testing
- **Surface every failure** — flag a failing test (even a seemingly unrelated one) with a one-line
  description and a proposed next step. Never fix it silently, skip it, or delete it to reach green.
- **Don't inline-pipe test output to `grep`/`head`/`tail`** — write the full output to a temp file,
  then search it. Truncated output hides the failures that matter.
- **Never pass `-x`/`--exitfirst`** to pytest — let the suite run to completion so every failure is
  visible at once.
