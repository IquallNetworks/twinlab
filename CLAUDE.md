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
backend now implements in full (twenty-four deltas; delta 12 is the async job model, delta 13 the
SSH jump, delta 14 the link table, delta 15 the cross-lab job listing, delta 16 job events on the
SSE stream — 14/15/16 approved 2026-07-30 — delta 17 test-suites v2, approved item-by-item
2026-08-03, delta 18 the device/image catalog, delta 19 the deployed-definition snapshot +
shared topology layout — both approved same day — delta 20 group canvas styling on the
layout resource, approved 2026-08-04, delta 21 the template library — input methods part
one, approved same day with the reviewer-directed per-kind split — and delta 22 config
import — input methods part two, approved 2026-08-04, design record in
`docs/config-import.md` — and delta 23 explicit wiring, which REVISED that
import surface the same day: the wiring list became a required input and
inferred adjacency was removed — and delta 24 batch runtime actions, approved
2026-08-04: the v1.0 remnant of the SHELVED scenario item, many netem
impairments + node power events in one request). Two non-compose
projects sit beside the services: **`client/`** (`twinlab-client`, the distributable async Python
client — PyPI-ready, published at v1.0) and **`blackbox/`** (the black-box test suite: 140 tests
exercising a live stack through the client only; all green, README documents env config and the
`deploy` marker). The suite is the contract's enforcement — backend changes are verified against
it, and contract changes go through review.

The project is a `docker compose` stack (`compose.yaml`, project name `twinlab`) of seven services:

- **`frontend/`** — Vite + React + TypeScript (pnpm). **Rebuilt in place on the v1.0 wire**
  (step 2 of the frontend rework, phased in `docs/frontend-rework.md`; **Phases 1–5 ALL done —
  frontend step 2 complete**. The parked backend batch is in progress — **link table + link oper
  state DONE 2026-07-30** (contract delta 14; the frontend gained a Links card on the Nodes tab,
  server-driven canvas edges with oper-state styling — stable `link:<linkindex>` ids, animated
  impaired edges, client parse as fallback — and edge-click per-endpoint netem via the extracted
  `NetemForm`/`useSetNetem` in `components/lab/netem-form.tsx`, which invalidates BOTH the node
  netem key and `['labs', name, 'links']`), and **cross-lab jobs + SSE job events DONE
  2026-07-30** (deltas 15/16: `lib/use-all-jobs.ts` is now ONE `GET /jobs` query instead of a
  per-lab fan-out — partial failure stopped being a state — and `useLabEvents` listens to the two
  NAMED events, so the jobs poll fell to a 15s fallback for the gap a reconnect leaves), and
  **host preparation DONE 2026-07-31** (the `hostprep/` sidecar + runner netns config path, both
  below: multi-access LAN topologies now deploy end-to-end — `examples/campus-lan.yml` is the
  worked example — and linux-node initial config actually applies), and
  **test-suites v2 DONE 2026-08-03** (contract delta 17 — see the backend bullet; the frontend
  panel was rebuilt on the v2 wire: CodeEditor JSON authoring, a Facts viewer dialog, rendered
  command + compare diff in results), and
  **device catalog DONE 2026-08-03** (contract delta 18: `GET /catalog` — the curated supported
  set with per-device netlab module support, default clab image, and best-effort image presence
  via the runner's `GET /images`, behind a `live` honesty flag; the builder's hardcoded
  `device-catalog.ts` became `use-device-catalog.ts` over the server list with a static fallback
  until the query settles, `parseBuildDoc`'s known-device gate is a parameter so the parse gate
  and palette share one list per mount, and palette/inspector flag a missing default image), and
  **deploy snapshot + shared layout DONE 2026-08-03** (contract delta 19: the lab header wears a
  `drifted` badge off `definition_drifted`, the Overview Definition card gains a **Changes** view
  — a dependency-free LCS line diff (`lib/diff.ts`) of deployed → stored — and manual topology
  arrangements moved server-side: `GET/PUT /labs/{name}/layout` replaces the localStorage
  `layout-store.ts` (deleted; `SavedPositions` now lives in `topology/flow-types.ts`), the Build
  tab is the ONLY layout writer (auto-PUT on drag end, full-replace) and the Overview canvas is
  **read/operate-only** — `nodesDraggable={false}`, it renders the shared arrangement and waits
  for the layout query to settle so the saved positions apply on first paint), and
  **template library DONE 2026-08-04** (contract delta 21 — see the backend bullet; the
  create-lab dialog gained a "Start from" selector composing create + PUT of the template's
  content, the builder's Add menu lists node templates stamped through `parseNodeFragment` —
  the same typed-vs-extras split the doc parser applies, so a stamped node is indistinguishable
  from a hand-authored one — the node inspector's General tab gained "Save as template", and
  the lab header wears a `template` badge with a publish-toggle dialog in its `⋯` menu; the
  library queries live under their own `['templates']` root so SSE lab bursts don't churn
  them), and
  **config import DONE 2026-08-04** (contract deltas 22 + 23 — see the backend bullet; the
  frontend gained the `/labs/import` wizard — gather sources with per-file device select →
  declare the WIRING (delta 23: prefilled from the server's suggestion, entries editable with a
  p2p/LAN badge; the import consumes only what the user confirms) → analyze via
  the pure factory → review warnings/renames/definition/per-node maps + carry + quarantine →
  create composes createLab → putCustomConfig → updateLabDefinition, custom config FIRST
  because the definition PUT validates its `config:` refs against the STORED fileset — plus an
  Import button on the labs page and the builder Add menu's "From config file…", which stamps
  the fragment through the shared `stampFragment` path and saves carry + quarantine into the
  lab's custom config UNATTACHED, since a single config infers no links and keeps SOURCE
  interface names); the parked batch
  (ROADMAP item 16, order agreed 2026-08-03/04 — builder link forms, both input methods
  and the aux-input analysis all landed 2026-08-04) closes with **batch runtime
  actions** (contract delta 24, in review — the v1.0 remnant of **scenarios**, which
  were SHELVED until after v1.0 at their design-discussion opening, groundwork
  recorded in ROADMAP 16.5); after it comes the **NOS platform
  sweep** (ROADMAP item 17, which since 2026-08-04 also carries the two reviews it
  informs — the `netlab up` parity gaps and the builder coverage review, run in
  parallel with it), then a
  comprehensive **Playwright e2e UX suite** (decided 2026-07-31, see ROADMAP —
  the browser-layer complement to the blackbox suite), and only then the v1.0
  release train (publish `twinlab-client` to PyPI + tag) goes LAST). Phase 1 (graphical
  identity):
  identities are CSS token packs
  keyed off `<html data-identity>`, **Schematic** (dark-first ink, amber signal, Space Grotesk +
  IBM Plex Mono, faint line-grid canvas) is the chosen design system and Blueprint is
  shelved-but-selectable; the twin-diamond wordmark is the logo; header chrome has its own
  `--id-header-*` tokens; fonts are self-hosted @fontsource (OFL); a dev-only `/styleguide`
  gallery renders every primitive. Phase 2 (IA + role-tailored surfaces): a **role-aware
  dashboard at `/`** (fleet stat tiles, recent operations across labs, recently-updated labs
  linking each caller to their tab, session-scoped SSE **activity feed** — module ring buffer in
  `lib/lab-event-store.ts`, no server history — and an admin card whose queries are
  permission-gated); **lab detail is routed tabs** under `/labs/$name` (layout route; children
  overview/build/nodes/operations/access; the index redirects role-aware via
  `defaultLabTab(lab.permissions)` — authors land on Overview, pure consumers on Nodes; Access
  renders only with `lab:grant`); a per-node **Connect drawer** (mgmt IP, web console + logs
  launchers, and SSH guidance from `lib/ssh.ts`: the `~/.ssh/config` `Host twinlab-jump` block +
  `ssh -J twinlab-jump <user>@<ip>` or the ProxyCommand one-liner — NEVER bare `-J` with `-i`,
  which dies at the hop; the Account page teaches the same block); a **jobs center at `/jobs`**
  plus per-lab job history through one shared `JobsTable` (row → detail sheet with request/
  result/error JSON; aggregation is one `GET /jobs` query keyed `['jobs', 'all', limit]`, under
  the same `['jobs']` root as the per-lab lists so one invalidation refreshes either). Long ops submit **202 async jobs** awaited via `waitJob`
  (`src/lib/api.ts`); the **test-suites** panel (rebuilt on the v2 wire 2026-08-03) and
  custom-config live on the
  Operations tab. **Whole-lab power + save-config are header-menu entries**, not a Controls card
  — `components/lab/lab-power-menu.tsx` renders them into the lab header's `⋯` menu above a
  separator from destroy/delete, each offered only where it acts (a MIXED lab shows both Start
  and Stop, since it has containers in both states; freeze and save name their reason when the
  lab has none running; destroy needs containers, delete does not). **Netem impairment is NOT a
  section of its own** either — it sits on the row it acts
  on, in the Nodes tab's two tables: the Links table's Impairment column expands into
  `LinkImpairment` (BIDIRECTIONAL — the same shaping written to every endpoint, Advanced splits
  per endpoint, divergent endpoints read "mixed"), and the Interfaces card (now ONE node at a
  time, behind a node selector) expands each row into a single-endpoint `NetemForm`
  (UNIDIRECTIONAL — netem shapes egress, so an interface IS a direction). Phase 3 (topology
  view): the stored definition renders on a React
  Flow + dagre canvas — `lib/topology.ts` best-effort-parses netlab's link
  forms (unresolvable entries surface as an "N links not rendered" strip, never dropped; LAN
  hubs for multi-access; drift shown both ways), live node state + netem badges overlay it
  (queries shared with the netem controls, running nodes only), selection reuses the connect
  drawer + node controls, and the toolbar does auto-layout, LR/TB and PNG export; undeployed
  labs render as documentation; manual layouts persist per lab in localStorage
  (`topology/layout-store.ts`, shared with the builder). The canvas is **Overview's Visual view**,
  not a tab of its own — `components/lab/definition-view.tsx` gives the Definition card the same
  Visual/Text selector the Build tab uses (Visual default, both read-only), since a separate
  Topology tab was a second surface over the same artifact; `/labs/{name}/topology` now redirects
  to overview so old links land. Phase 4 (guided builder): a **Build tab**
  (`lab:edit`) owns definition editing in two modes — Visual is an editable canvas + inspector
  over `lib/build-doc.ts`, a **typed core + lossless extras passthrough** (reworked 2026-08-03
  from the original strict-subset gate, maintainer-directed): the typed core is nodes,
  **links** (stub/p2p/LAN by ENDPOINT COUNT — since 2026-08-04 the dict AND interfaces forms
  parse, endpoints discriminated via the declared-node set exactly as netlab does, each link
  carrying a typed `name` plus verbatim link-level and per-endpoint extras; emit re-spells
  interfaces form as the equivalent dict form — netlab expands both identically, verified live
  — while bare links keep the terse `a-b`/list spellings; one-endpoint stubs render as small
  terminator canvas nodes, `stub:<n>` session ids), **groups** (first-class 2026-08-03 —
  members + `config` template attachment; anything
  else a group broadcasts rides its extras), the proven ospf/bgp/mpls/vrf set, curated
  `lib/device-catalog.ts` with the module-support matrix, plus the server-injected
  name/addressing keys — and every key OUTSIDE it (unknown top-level keys, unknown node
  attributes, overflow forms like `bgp: {as, router_id}` or a vrf with `rd:`) lands VERBATIM in
  `extras` at the lab/node/group/link/endpoint level, edited as YAML in the inspector's
  "Advanced properties"
  sections (`build/extras-editor.tsx`). ONE shape classifier decides typed-vs-extras for both
  the parser and the editors, so a key never lives in both places (typed controls whose key the
  extras own disable with a pointer; an edge-path same-key collision is an emit-time save
  blocker). **The Tier A batch (ROADMAP 17.3) shipped 2026-08-04**, so `parseBuildDoc` now
  gates only on what NETLAB itself rejects — invalid YAML, attribute-only link entries,
  interfaces mixed with node keys, undeclared link endpoints, a name outside netlab's id rule
  (`[A-Za-z_][A-Za-z0-9_-]{0,15}` — hyphens legal, 16 chars) — plus the unknown-device POLICY
  gate (the NOS-sweep boundary, deliberately not passthrough). Everything else netlab accepts
  now parses: `nodes:` as a mapping or EITHER list form, list-form link members as bare names
  or `{node, …}` records, **self-links** (a node twice on one link — endpoints are addressed
  by POSITION throughout the reducer/inspector/canvas, emit uses the list form when bare and
  the interfaces form when attributed, and the canvas draws a loop since both handles sit at
  the node center), the **dict-of-lists `links:`** form (the sub-list name rides a typed
  `listName` so a save re-emits the grouping; all-or-nothing, a mixed doc is an emit blocker),
  **link groups** (expanded on parse exactly as netlab's expand_groups does — group data
  copied down, member data winning — proven to yield a byte-identical expanded topology), and
  **component-expanded endpoints** (`<node>_<member>` where the node has `include:` — netlab's
  is_nodename_valid prefix rule; such a node needs no device, and the endpoint gets a
  read-only canvas placeholder that selects its includer). Because a save can now REWRITE a
  document, parse returns `notices` (link group expanded) beside the gating `reasons`.
  `emitBuildDoc` stays canonical with the round-trip invariant parse(emit(doc)) == doc (extras
  key order ignored), and emit problems (device-less node — waived for an `include:` node —
  2-member LAN, a group member that is neither a declared node NOR another group (netlab
  groups nest; waived when the group sets `_auto_create`), a mixed named/unnamed link list, a
  link extras key naming ANY declared node, which would re-parse as an endpoint) BLOCK
  Save loudly; the reducer (`build/build-state.ts`) owns the doc (group
  add/rename/delete/patch, nested memberships migrating on rename/delete; link
  name/extras/endpoint patches + add-stub; node rename/delete
  keeps memberships and link endpoints consistent), the canvas
  derives from it
  (drag-to-connect via `validateConnect`, palette adds, index-safe deletions), and the
  inspector greys out device×module combinations the catalog says can't run. The
  mpls-l3vpn.iol example — `groups:` block included — AND campus-lan.yml (dict-form links,
  stub, attributed LAN) are fully buildable visually. Text mode
  is the full-syntax escape hatch (the old EditDefinitionDialog is gone). Saves PUT the emitted YAML;
  `netlab_invalid` renders as a panel with the envelope's `extras.stderr` (`ApiError` carries
  extras). Unsaved changes get a router blocker + beforeunload guard. The parser/emitter's invariants are guarded by **`pnpm check:build-doc`** (`frontend/scripts/`) — 36 round-trip/gate/blocker checks incl. all three `examples/` definitions, bundling the pure module with vite's own API and running it under plain node, since the frontend has no test runner. Phase 5 (editor +
  polish): a shared **`CodeEditor`** (`components/code-editor.tsx`, hand-rolled CodeMirror 6
  wrapper — controlled value with an echo guard, compartments, minimalSetup + explicit
  extensions, themed purely from identity CSS vars with three `--id-code-*` syntax tokens)
  powers the Build text mode (yaml + client-side lint gutter via `parseDocument`; Save is NOT
  lint-gated — the server's dry `netlab create` stays the validator; netlab stderr stays a
  panel since it carries no positions), the Overview definition card (read-only yaml) and
  custom-config (jinja2 sources read-only, templates dialog as linted json). A **cmdk command
  palette** (Ctrl/Cmd+K, mounted in the app shell, defers to an open xterm) does gated page
  nav, current-lab tab jumps, fuzzy jump-to-lab, Create lab (`/labs?new=1` search param opens
  the page-controlled dialog), theme, and sign out (shared `useLogout`) — no lifecycle verbs.
  Teaching empty states (builder-canvas overlay, created-lab steps, dashboard CTA, jobs line);
  router default error/not-found pages; honest error states (lab-access failures don't read as
  "no grants"; `useAllJobs` renders partial data with a `failedLabs` count, isError =
  all-failed; Retry affordances); a11y pass (aria-labels beside titles, keyboard job rows,
  login h1, labeled canvases); TwinGlyph SVG favicon + meta/theme-color + `useDocumentTitle`;
  computed contrast audit fixed Schematic light (`--primary`/`--ring` L→0.64,
  `--id-code-key` toward ink). UI stack: **shadcn/ui**
  (radix base) on Tailwind v4, the
  **TanStack** family (Query, Router in code-based mode, Form) and **zod**. Auth gate: a pathless
  layout route resolves `GET /auth/me` in `beforeLoad`, redirects to `/login` on 401; actions
  gate on the caller's permissions. `useLabEvents` records SSE events to the activity store and
  invalidates the `['labs']`/`['jobs']` query roots. API access goes through the typed,
  zod-parsed client (`src/lib/api.ts`) raising the `{code, message, extras}` envelope as
  `ApiError`; dev server proxies `/api/v1` (`VITE_PROXY_TARGET`, default
  `http://localhost:8000`). Gates: `pnpm typecheck` + `pnpm build` + `pnpm check:build-doc`.
- **`backend/`** — FastAPI (uv, **Python 3.14**, ids are stdlib **UUIDv7**). Turns a declarative
  netlab definition into a running lab: runs `netlab create` to generate a containerlab topology,
  then deploys it through the clab-api server (piped inline as `topologyContent`); the generated
  `node_files/` tree is materialized per lab on the host-shared `LAB_FILES_DIR` and the topology's
  relative binds (and any relative `startup-config`) are REWRITTEN absolute onto it — same-path
  invariant, dockerd mounts and clab-api pre-flights the identical path — so bind-delivered
  artifacts (the all-nodes `/etc/hosts`, frr's daemons file, sh-mode config scripts) survive
  inline deploy; destroy best-effort removes the regenerable tree, and with the env unset binds
  are stripped as before (hand-rolled setups). Config push is
  delegated to the netlab-runner. **Every non-2xx wears one error envelope** `{code, message,
  extras}` (`api_errors.py`: ApiError + handlers covering FastAPI validation and framework errors;
  stable code slugs like `lab_not_found`, `permission_denied`, `netlab_invalid`). **Lab lifecycle
  is split** (create → author → deploy): `POST /labs {name}` creates a bare record (status
  `created`, no definition) and allocates the lab's management `/24` from `MGMT_SUBNET_POOL` up
  front; `PUT /labs/{name}` authors/replaces the stored definition (validated by a dry `netlab
  create`; the record's name and subnet are re-pinned into it — `set_lab_name`/`set_mgmt_subnet`,
  an explicit `addressing.mgmt.ipv4` wins; legal netlab keys Twinlab does not honor — `tools:`,
  `defaults.netlab.up/down` shell hooks, OVS `bridge_type` — are 422 `unsupported_directive`
  rather than silently ignored, and the definition's top-level `message:` rides `LabDetail` —
  up-parity gaps 2/5/6/7, decisions in `docs/nos-sweep/`); `POST /labs/{name}/deploy` is the ONLY deploy verb —
  from the stored definition, fresh or overwrite-in-place, opt-in `configure`; 409 `no_definition`
  on an unauthored record; the deploy job's first step is an **image pre-flight** (gap 3): a
  missing image whose device the catalog marks `local_only` (iol) fails fast with a friendly
  `image_missing` job error, missing-but-pullable images only warn (`DeployResponse.warnings`),
  and a runner outage skips the check. **The four long operations (deploy/configure/destroy/suite-run) are
  ASYNC JOBS** (contract delta 12): pre-accept checks stay synchronous, then the route returns
  **202 + a running Job** and the work runs in an in-process task; callers poll `GET
  /labs/{name}/jobs/{id}` (+ `GET .../jobs?limit=`, both `lab:read`, readable on a soft-deleted
  lab so a destroy-with-remove job stays pollable; a revived name starts with no history) — or
  watch the SSE stream's `job` events (delta 16, below). **`GET /jobs?limit=`** (delta 15) is the
  cross-lab listing: recent jobs over every lab the caller may read, newest first, one indexed
  query filtered by the events stream's readable-lab set (any authenticated user; no lab is named,
  so nothing to hide behind). Jobs of REMOVED labs are excluded there, so the fleet list follows
  `GET /labs` and a revived name keeps its empty history. Jobs
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
  /auth/password` self-change that keeps the calling session, **API keys** — `POST/GET/DELETE
  /auth/api-keys`, sha256-stored Bearer secrets shown once, dead when their user is deactivated or
  deleted — and **SSH keys** — `POST/GET/DELETE /auth/ssh-keys`, registered public keys for the
  jump host (delta 13): pure-stdlib parse + SHA256 fingerprint, fingerprints globally unique, 422
  `invalid_public_key`/`unsupported_key_type`, 409 `name_taken`/`key_already_registered`; plus
  `POST /auth/ssh-keys/generate` — a server-side ed25519 pair via an ssh-keygen subprocess
  boundary, one TemporaryDirectory per call so concurrency needs no lock, private key returned
  once and never stored), `GET
  /ssh-access` (advertised jump coordinates from `SSH_JUMP_ADDRESS`; `enabled:false` when unset),
  `GET /internal/ssh/authorized-keys` (NOT under `/api/v1`, so the frontend proxy can't expose it;
  `X-Jump-Token` guard — sshd's AuthorizedKeysCommand calls it per connection and gets one
  authorized_keys line: `restrict,port-forwarding` + `permitopen="<ip>:*"` per node of the owner's
  `lab:terminal` labs; **fail-safe invariant: an empty permitted set returns an EMPTY body**, never
  a permitopen-less line, because sshd treats missing permitopen as forward-anywhere; clab failure
  → 502 so the lookup script fails closed), `users/*`
  (list/create/get/roles/password-reset/activate-toggle/delete, with a
  **last-admin guard**: 409 on deactivating or deleting the only active admin), `groups/*`,
  `roles`, `principals`, **`GET /catalog`** (delta 18: the deployable-device catalog — curated
  supported set (`services/device_catalog.py`), per-device module support under the clab provider
  and default clab image both mirrored from the installed netlab with drift-guard tests, plus
  best-effort image presence via the runner's `GET /images` — matching policy stays in the
  backend, untagged names normalize to `:latest`; runner unreachable degrades to
  `image_present=null` + `live=false`, never an error; any authenticated user),
  the **template library** (delta 21: TWO sibling collections with independent namespaces —
  `GET /templates/network` (+`/{name}`) serves the builtin tier (packaged mirrors of
  `examples/` in `services/network_templates.py`, drift-guard test keeps them byte-identical)
  merged with PUBLISHED labs, each user-tier entry a LIVE view of its lab's stored definition
  (published via `PUT /labs/{name}/template` — `template:manage` + `lab:read`, existence-hiding
  checked FIRST; description required at publish, 409 `no_definition` on a bare record, 409
  `name_taken` against a builtin; soft-delete and name revival withdraw, migration 0019); and
  `GET/POST /templates/node` + `GET/PUT/DELETE /templates/node/{name}` — snapshot node
  fragments, STRUCTURAL validation only (YAML mapping naming `device`, 64KB bound → 422
  `invalid_template`; the receiving lab's PUT stays the real validator), `device` denormalized
  for the list, the builtin node namespace reserved-but-empty. Reads any authenticated user;
  mutations ride the NEW global-only `template:manage` (admin + global_operator);
  `LabDetail.template_published` renders the toggle; NO instantiate verb — clients compose the
  lifecycle),
  **config import** (delta 22, design record `docs/config-import.md`: `POST /import/network` —
  global `lab:create`, sync — and `POST /import/node` — any authenticated — are PURE definition
  factories in `services/configimport/`: per-platform boundary parsers (VyOS set+brace own code;
  IOS over netutils, Apache-2.0, with a local `typings/` stub since ConfigLine is an untyped
  namedtuple) → subnet-join link inference (2=p2p, 3+=LAN, 1=stub; mgmt-VRF interfaces never
  join) → THIN skeleton emission (nodes/links/pinned addressing, NO modules) → the same dry
  `netlab create` a PUT runs, whose expanded topology yields the source-if→lab-if map joined on
  PINNED addresses → carry rewrite (IOS single-pass alternation over names+abbreviations so
  shifted maps can't cascade; VyOS structural token rewrite incl. the ethernet→dummy type change
  stubs force — VyOS stubs realize as `dumN`, loopback pins as `dum0`, IOL stubs as real
  `EthernetX` via clab dummy links, all live-probed). Every source line lands in EXACTLY ONE of
  modeled/carried/quarantined (partition is a tested invariant); carry files are
  `imported/<node>.j2` (`{% raw %}`-wrapped, referenced by the definition) and quarantine files
  sit beside them UNREFERENCED; quarantine classes mgmt/auth/telemetry/hardware are pinned
  vocabulary, the line lists are code. COMPOSE ORDER: put_custom_config BEFORE
  update_definition — the PUT's dry create validates `config:` refs against the STORED fileset
  (live-proven). `POST /labs/{name}/config-diff` (lab:validate, deployed lab) is the STATELESS
  fidelity proof: collects running configs over the runner exec transport (VyOS needs
  `/opt/vyatta/bin/vyatta-op-cmd-wrapper` — bare op-mode commands return empty over docker
  exec) and classifies every comparable source line matched/missing/extra modulo quarantine +
  an address-join map recompute; informational, never a gate. 422 slugs `unsupported_device` /
  `config_unparseable` / `duplicate_node` (+ `netlab_invalid` with stderr); `CatalogDevice`
  gained `config_import`, derived from the parser set. **Delta 23 revised this the same day:**
  `wiring` is a REQUIRED input of `POST /import/network` and inferred adjacency is GONE —
  topology is intent, so a link exists because the caller declared it. Each entry lists
  `node:interface` endpoints (SOURCE names, first-colon split so channelized names survive;
  count decides — 2 p2p, 3+ LAN), an all-unaddressed wire emits a `prefix: false` L2 link (the
  unnumbered-core / trunk / LAG-member case addressing can never see; LAG needs nothing special
  — wire the members, the bundle rides the carry), and a MIXED wire spells `ipv4: false` on its
  unaddressed endpoints because netlab otherwise INVENTS an address for them (live-proven, and
  not even from the pinned prefix). What is NOT adjacency stays automatic: loopback pins, mgmt
  quarantine, and an addressed interface in no wire becoming a STUB (the twin's boundary).
  Contradictions are ERRORS now — 422 `wiring_invalid` (unknown node/interface, an interface
  wired twice, <2 endpoints, loopback/mgmt endpoints, self-links) and `wiring_conflict`
  (endpoints in different subnets — the mask-typo catch), both carrying the offending `entry`
  index in extras. The subnet join survives ONLY as advice: `POST /import/wiring-suggestion`
  (`services/configimport/suggestion.py`) proposes wiring for a client to prefill an editor
  with and is never consumed implicitly. `DiffSource.interface_map` overrides the diff's
  address join for L2-linked interfaces, which carry no address on either side),
  `GET /labs` + `GET /labs/{name}` (stored record merged with best-effort
  live node state; owner as `Principal {id, name}`, `config_time_status` tri-state, per-lab
  `permissions` MASKED to the lab-scoped set; **delta 19**: both carry `definition_drifted` —
  non-None only while `deployed` — and the detail serves `deployed_definition`, the snapshot the
  deploy job writes from the text it ACTUALLY deployed (a PUT landing mid-deploy must not leak
  in), cleared on destroy; drift is exact text equality, and since PUT normalizes the stored
  definition (YAML re-dump while re-pinning name/subnet) comment/formatting edits normalize away
  — only changes that survive normalization flag, live-verified; a hint, never a gate), and
  **`GET/PUT /labs/{name}/layout`** (delta 19: ONE shared manual topology arrangement per lab —
  `{canvas-id: {x, y}}`, ids OPAQUE presentation data never validated against the definition;
  GET `lab:read` and never 409s (an empty layout is honest), PUT `lab:edit` full-replace with
  shape-only bounds — ≤512 keys, ≤128 chars, finite floats; **delta 20**: the resource also
  carries `groups` — per-group styling keyed by group name, `color` pinned to `#rrggbb` —
  because presentation belongs on the layout, not in the definition netlab validates). **Test suites v2** (contract delta 17, shipped
  2026-08-03 — Twinlab's own validation, not `netlab validate`, see ROADMAP item 15): declarative
  assertions stored on the lab record (never sent to `netlab create`), each test a **render →
  execute → parse → assert pipeline**, all data, no user code. A test's `run` is one `TestCase`
  `{command, expect, parse, interactive}` or a DEVICE-KEYED dict of cases (one suite serves the
  VyOS and IOL flavors; a node whose device has no case reports `skip`). Commands and expectation
  strings carry Jinja2 templates rendered per node against the lab's **fact namespace** — netlab's
  RAW node dicts from the expanded topology (PROVISIONAL, pinning is a pre-v1.0 decision), served
  by `GET /labs/{name}/facts` (lazy-backfilled JSONB cache like the link table) with one `address`
  filter; rendering is sandboxed + StrictUndefined, PUT syntax-checks always and dry-renders when
  facts exist (422 `template_invalid` naming suite/test/field). `parse` is `json` (free on VyOS —
  FRR's `vtysh -c "show … json"`, incl. `show bgp ipv4 vpn summary json`; the `vpnv4 unicast`
  spelling doesn't exist) or `textfsm` (ntc-templates' cisco_ios set overlaid by Twinlab-packaged
  templates in `services/textfsm_templates/` — e.g. our own `show mpls ldp neighbor`; a missing
  template/failed parse is an `error` result, NEVER a silent raw fallback). `expect` is exactly one
  of contains/not_contains/matches/`compare` — compare pairs with parse (both ways, server-checked)
  and asserts via `napalm.base.validate.compare` (nested partial match, `_mode: strict`, numeric
  operators; napalm MUTATES its args — deep-copy first; the structured diff lands on
  `TestResult.diff`, the RENDERED command on `.command`). `interactive: true` routes SSH-transport
  nodes through a persistent netmiko channel in the runner (host/creds via `ansible-inventory
  --host`; IOS truncates `ping … repeat` on a one-shot exec — proven side-by-side) and is a
  deliberate no-op over docker exec. Suite `stage` semantics are unchanged (`config-time` gates a
  configure, skip RETAINS the prior gate, failure = deployed + `validation_failed`); the pipeline
  lives in `services/validation.py`, results persist per-suite in `last_validation`, and
  `examples/mpls-l3vpn.test-suites.json` is ONE device-keyed file serving both MPLS labs with every
  address rendered from facts (verified live: 25/25 + interactive VRF pings on IOL). Local
  `typings/` stubs give the untyped napalm/textfsm/ntc imports precise types. **HTTP errors mean
  "could not run"**: a config push that ran but failed on ≥1 node is a 2xx `status="config_failed"`
  with per-node results.
  **Runtime control/observability** over live clab-api state (not
  the definition): `POST /labs/{name}/nodes/{node}/{start|stop|restart|pause|unpause}` and
  `POST /labs/{name}/{start|stop|restart}` (power control), `POST /labs/{name}/{pause|unpause}`
  (whole-lab freeze — clab-api has no lab-level pause, so this fans out over the nodes, non-atomic),
  `POST /labs/{name}/save` (persist running config), `GET /labs/{name}/nodes/{node}/logs` (container
  logs, `?tail=`), `GET /labs/{name}/interfaces` (per-node inventory keyed by SHORT node name;
  `?node=` filters by it), the **link table** `GET /labs/{name}/links` (contract delta 14: the
  LOGICAL link list from netlab's expanded topology — a LAN is ONE link with N endpoints; `netlab
  create` runs `-o config -o provider -o json:nodefault=` since `-o` REPLACES the default output
  set and `config` must come first for the clab provider's bind validation; persisted as a
  regenerable JSONB cache on the lab record by the PUT dry-run, refreshed on deploy, lazily
  backfilled on GET; endpoints carry the container-side interface name — `clab.name`-else-`ifname`,
  live-resolved by name-OR-alias so cisco IOL's `Ethernet0/1` resolves to the netns `eth1` — plus
  netlab IPs, live `state`, and the active netem impairment, merged best-effort with ONE inspect +
  SEQUENTIAL netem shows because clab-api serializes netem per lab, concurrent calls 409; derived
  `oper_state` is a pinned up/degraded/down/unknown roll-up, `live` the honesty flag, 409
  `no_definition` on a bare record, upstream failures degrade to `live=false` — never 5xx; netlab's
  link `type` is a passthrough and NOT a rendering signal — a linux-host p2p comes out "lan",
  consumers discriminate on endpoint count), and **netem link impairment** keyed by node+interface (`GET/POST
  /labs/{name}/nodes/{node}/netem` — durations are structured `{value, unit}` pairs; set has
  REPLACE semantics: the body is the complete desired impairment, omitted = cleared, empty body =
  clear all; show lists only ACTIVELY impaired interfaces — the node's container is resolved from
  live state, and these routes precede the `{action}` node route so `netem` isn't captured by the
  action path param), and **batch runtime actions** (delta 24: `POST /labs/{name}/actions`,
  `lab:configure` — many netem sets/clears + node power events in ONE request, so a caller stages a
  whole degraded condition without round-trip choreography. Items are TYPE-UNIFIED with the single
  verbs, not route-merged: `NetemActionItem` INHERITS `NetemSetRequest` (+`node`+`kind`), the
  `NodeAction` vocabulary lives in `models.py`, and `_netem_once`/`_power_once` are ONE executor
  the single routes and the batch share — a standalone verb is a batch of one. Sequential in
  request order, CONTINUES past failures: a 2xx means the batch RAN and the index-aligned report
  carries each item's outcome, while structural problems 422 up front with nothing executed.
  Explicitly not a transaction — no rollback, no isolation; ≤64 items; sync, so runtime control
  stays available while a job holds the per-lab mutex. ONE inspect resolves every netem item's
  container — power items take short names, so they survive an inspect failure and a power-only
  batch never inspects). Node state carries a docker-vocabulary `state` (unknown upstream values 502
  loudly) and
  the management IP (`mgmt_ip`, from clab's `ipv4_address`) for a copy-paste `ssh` command. A
  **Server-Sent Events** stream at `GET /events` (`lab:read`) carries TWO **named** events
  (contract delta 16): `lab` relays clab-api's live container events (distilled to
  `{lab, node, action, timestamp}`) and `job` announces a job's submit and terminal state
  (`{lab, job_id, kind, status, timestamp}` — a poke, never the result/error, which stay on the
  record). Job events are born in-process, so they travel over a deliberately LOSSY broker
  (`services/job_events.py`, one bounded queue per open stream): a stream that stopped reading
  drops events rather than stalling the job runner. Both are filtered to the caller's readable
  labs, auth resolved up front so the long-lived connection doesn't pin a DB session. There is NO
  replay (no Last-Event-ID), so a reconnect misses whatever happened while it was down — consumers
  watching a running job keep a slow fallback poll. A **web terminal**
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
  `lab:destroy`, `lab:grant`; global-only `lab:create`, `user:manage`, `group:manage`,
  `template:manage` (delta 21 — authors the template library's user tier; reads need no
  permission). The clab-api
  client (`services/clab_api.py`) routes every authenticated call through one `_authed` helper.
  Errors-as-values throughout; `try`/`except` only at the subprocess/httpx/pydantic boundaries.
- **`netlab-runner/`** — FastAPI (uv) config-push sidecar. `POST /configure {definition}` runs
  `netlab create` (regenerate the inventory) then `netlab initial`, which drives Ansible over the
  `docker` connection (exec into `clab-<lab>-<node>` by name via the mounted Docker socket — no host
  network). Returns structured per-node results (parsed from Ansible's PLAY RECAP). netlab
  (MIT) is aggregated with ansible-core + community.docker (GPLv3) as separate processes.
  **Plain-container nodes (linux, daemons) are NOT configured over Ansible**: netlab deploys their
  config as host-side scripts via `sudo ip netns exec clab-<lab>-<node>` (the runner's full
  iproute2/procps against the node's netns — alpine node images only carry busybox), so the runner
  carries host pid namespace, SYS_ADMIN + SYS_PTRACE + NET_ADMIN, `/var/run/netns`, and
  apparmor/systempaths unconfined (see compose comments; the Docker socket it already holds is
  root-equivalent, so none of this widens its reach). Script-configured nodes never appear in the
  PLAY RECAP, so they are absent from per-node results; their failures surface through netlab
  initial's exit code as `status="config_failed"`.
- **`hostprep/`** — FastAPI (uv, Python 3.14) host-preparation sidecar: the ONE component allowed
  to touch host network devices. Does `netlab up`'s clab pre-start work, which Twinlab otherwise
  never runs: creates/deletes the **host Linux bridges multi-access (3+ endpoint) links need**
  (`name[0:10]_linkindex`; `ip link add` + up + `group_fwd_mask 65528` via netlink — the
  container's /sys is read-only) and **modprobes kernel modules** (mpls/vrf/vxlan/lag + device
  extras; never unloads — host-shared). A dumb, stateless executor behind `X-Hostprep-Token`
  (compose-required `:?` secret): strict validation before any command (bridge-name regex bounded
  to IFNAMSIZ, fixed module allowlist), fixed-argv subprocess only, per-item outcomes as data
  (`created`/`existed`/`in_use`/`not_bridge`/...). Runs `network_mode: host` (bridges live in the
  host netns) with `cap_drop: ALL` + exactly NET_ADMIN + SYS_MODULE, `/lib/modules:ro`, **no
  Docker socket, no netlab, no definitions**; port 8091 beside clab-api's 8090, reached via the
  same host-gateway pattern. ALL policy lives in the backend: the deploy job derives
  `host_bridges`/`kernel_modules` from the expanded topology (`ClabArtifacts`; the kmods map is
  mirrored from netlab's defaults with a drift-guard test), refuses **bridge-name collisions**
  (names truncate the lab name to 10 chars — two labs sharing a prefix and linkindex would be
  silently cross-wired by netlab itself; Twinlab 409s `bridge_conflict` off the persisted claims),
  records the claim on `labs.host_bridges` BEFORE deploying, prunes stale names after a redeploy,
  and releases it at destroy only when the bridges are confirmed gone (a failed cleanup fails the
  job loudly and keeps the claim for retry). Deleting refuses a bridge with attached ports —
  after a clean destroy the veths are gone, so ports mean someone else is wired to it. Job error
  slugs: `hostprep_unavailable`, `hostprep_failed`, `bridge_conflict`, `kernel_module_missing`.
  A stack without the sidecar still deploys every lab that needs no host prep.
- **`jump/`** — the SSH jump host (delta 13): stock OpenSSH sshd (debian:trixie-slim, BSD-licensed)
  publishing `JUMP_PORT` (default 2222). One forwarding-only system account (`jump`, nologin, no
  PTY/agent/X11/sftp); per-key access is resolved LIVE by `AuthorizedKeysCommand` → the backend's
  `/internal` lookup (shared `JUMP_TOKEN`, required via compose `:?` so the stack can't start with
  a well-known secret), so revoking a key/grant/user bites on the next connection — no per-user
  provisioning in the container. Host keys persist on the `jump_hostkeys` volume (a recreate must
  not look like a MITM). Sits on the plain compose network: containerlab's iptables rules make lab
  mgmt bridges reachable without host networking (same mechanism the runner's IOL SSH push relies
  on). Users connect with plain `ssh -J jump@host:2222 <node-user>@<mgmt_ip>` — Ansible-ready.
- **`clab-api`** — the containerlab API server (`srl-labs/clab-api-server`, Apache-2.0), host-coupled
  (host network + PID, Docker socket and PAM databases mounted); it deploys lab nodes as sibling
  containers on the host daemon and authenticates a host user in the `clab_api` group.
- **`postgres`** — backs the RBAC store (users, roles, permissions, sessions) and the durable lab
  records (`labs`: definition + status + owner) via SQLAlchemy async + Alembic; migrations run in the
  backend entrypoint.

Also present: `LICENSE` (Apache 2.0). Backend + netlab-runner + hostprep quality gates: `ruff
format` + `ruff check`, basedpyright (strict), pytest.

**Supported NOS platforms are VyOS, Cisco IOL, FRR and MikroTik RouterOS 7 (CHR), plus the
bird and dnsmasq daemons and `linux` as the host/endpoint device — the tested set** (the
2026-07-31 vyos+iol call, widened 2026-08-04 by the sweep's rule that everything probed green
gets admitted; per-platform evidence in `docs/nos-sweep/results.md`). The builder's device
catalog offers exactly these. Other netlab devices are out of scope for now, not merely
unpolished. The old hard blocker is gone: netlab delivers some config as `node_files/*` clab
binds, which inline deploy used to strip — since 2026-08-04 the deploy job **materializes that
tree onto the host-shared `LAB_FILES_DIR` and rewrites the binds absolute** (same-path
invariant: one path on the host and in the backend and clab-api mounts; see compose), so
bind-delivered config works — which is what unblocked FRR and the daemons. A definition naming
another device is not rejected — it edits as text and may even deploy — but nothing about it is
promised. **`kind` is deliberately NOT admitted**: containerlab's `k8s-kind` names the
container `<node>-control-plane`, outside clab's `clab-<lab>-<node>` convention, so the
live-state merge cannot see it (missing from the node list, links `unknown`).

**Admitting a platform is FOUR coordinated changes, not a catalog edit** (the full procedure,
with every trap's failure signature, is `docs/nos-sweep/admitting-a-platform.md`): (1)
`services/device_catalog.py` `SUPPORTED_DEVICES` + the frontend's `use-device-catalog.ts`
static fallback; (2) backend `DEVICE_KMODS` **and** hostprep's fixed module allowlist together
(the drift guard only covers the netlab side); (3) **the netlab-runner's Ansible collection for
that platform's transport** — the Dockerfile installs one per transport, and a missing one
fails as `network os <x> is not supported` + UNREACHABLE *after* netlab has rendered the config
fine, so it reads like a device fault and is not. Docker-exec platforms (vyos, frr, linux,
daemons) need no collection; `network_cli` ones do (cisco.ios for IOL, community.routeros for
CHR); and (4) a connection override in `netlab-runner/netlab-defaults.yml`
(`/etc/netlab/defaults.yml`, merged over netlab's device data at create time) where netlab
names a plugin ansible-core no longer ships — it removed `paramiko` in 2.21, which netlab still
uses for openbsd/srlinux/sros. Widening the set is a maintainer decision that starts with testing —
a pre-v1.0 **NOS platform sweep** (ROADMAP item 17, added 2026-08-03, opened 2026-08-04 — the
three analyses, the decision log and the probe results live in `docs/nos-sweep/`) is exactly
that testing: obtain and exercise as many containerlab-kind NOSes as possible (images are used,
never distributed) to confirm or deny support and shake out bugs before the release.

**End-to-end deploy + config push is proven:** create → `PUT` the definition → `POST
/labs/{name}/deploy` with `configure: true` (202 + job) → poll the job to `succeeded` → nodes
deployed *and* configured via clab-api deploy + the netlab-runner, config-time gate green —
exercised continuously by the black-box suite's `deploy`-marked tests (linux nodes, incl. the
multi-access-LAN bridge path) and verified on VyOS (OSPF adjacency reaches Full), cisco IOL,
FRR, bird and MikroTik CHR (all reaching OSPF Full).
Needs a host user in the `clab_api` group, node images pulled, and clab-api running. Keep this
section current as the project evolves.

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
