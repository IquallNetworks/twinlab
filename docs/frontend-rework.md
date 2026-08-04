# Frontend rework, step 2 — the rebuild

Definition + phased roadmap for the from-zero frontend rebuild (step 2 of the two-step rework;
step 1, the v1.0-wire prototype, is done). This file is the working agreement: scope, decisions,
phases, and the backend/whole-project items deliberately parked for later.

## Goals

1. **A distinct graphical identity** — the current UI is generic shadcn defaults ("obviously
   AI-generated"). The rebuild commits to a designed point of view.
2. **Role-tailored UX** — the same app must serve four kinds of users well: admins (user/group
   management), lab managers (author/deploy/operate), lab consumers (connect to nodes, nothing
   else), and viewers (read-only observation).
3. **A guided lab builder** — "add node → pick device/image → drag to connect", emitting a netlab
   definition.
4. **A graphical topology view** — nodes, links, live state, impairments, on an interactive
   canvas.

## Locked decisions

- **Keep the wire layer, rebuild the UI from zero.** `src/lib` (typed API client, zod schemas,
  query options, SSE hook) is v1.0-correct and smoke-tested — it stays. Every page, component,
  and style is rebuilt.
- **Phase 1 is an identity bake-off**: all three candidate directions get a basic-but-complete
  PoC; the user picks the winner before any further phase begins.
- **Canvas library: React Flow** (`@xyflow/react`, MIT) for both the topology view and the
  builder — one library, small graphs, interaction-first. Auto-layout via `@dagrejs/dagre` (MIT).
  (Cytoscape.js was considered; it wins only for large analysis graphs, not our case.)
- **Approved dependencies** (added via pnpm only when their phase starts, never hand-pinned):
  `@xyflow/react` (MIT) + `@dagrejs/dagre` (MIT), `yaml` (ISC), CodeMirror 6 (MIT), `cmdk` (MIT).
- **Test-suites UI is frozen.** The suite mechanism is being reworked backend-first later; the
  rebuild carries the existing panel over untouched (or hides it), and no new suite UX is
  designed now.

## Personas → surfaces (RBAC we already have; no backend needed)

The UI adapts off `me.permissions` plus each lab's masked per-lab `permissions` — both already
on the wire.

| Persona | Signals | What they get |
| --- | --- | --- |
| Admin | `user:manage`, `group:manage` | Administration area (users, groups, roles), fleet overview |
| Lab manager | `lab:create`/`edit`/`configure`/`destroy`/`grant` | Builder, definition editor, deploy/operations, grants |
| Consumer | `lab:terminal` (± `lab:configure`) | Connect-focused lab view: node states, web console, SSH guidance |
| Viewer | `lab:read` only | Read-only topology + state, activity feed |

One app, not four: a role-aware dashboard, permission-filtered nav, and a lab detail split into
tabs (**Overview / Topology / Nodes / Build / Operations / Access**) where tabs and actions
appear only when permitted. A pure consumer opening a lab lands on connect, not authoring.

**Carried-in requirement (user-confirmed):** the SSH connect guidance must stop suggesting bare
`ssh -i … -J jump@host:port <ip>` — `-i` never reaches the `-J` hop, so it fails for every
registered/generated key. The rebuild offers a copyable `~/.ssh/config` block
(`Host twinlab-jump` / HostName / Port / User jump / IdentityFile / IdentitiesOnly yes) plus
`ssh -J twinlab-jump <node-user>@<mgmt-ip>`, with the ProxyCommand one-liner as the alternative.

## Phases

### Phase 1 — graphical identity PoC (bake-off)

Three candidate directions, each executed as a basic-but-complete PoC on the same rebuilt
skeleton, so the comparison is apples-to-apples:

1. **Schematic, dark-first** — engineering-schematic language (dot-grid canvas, ruled lines,
   device glyphs, mono-accented type), near-black ink, one signal accent, proper light theme.
2. **Control room** — dense terminal-adjacent NOC: near-black, phosphor green/amber accent,
   heavy monospace, data-first tables.
3. **Blueprint** — light-first engineering drawing: graph-paper grid, ink blue on paper white,
   drafting annotations; dark as the secondary variant.

Mechanics: identities are **token packs** (Tailwind v4 CSS variables: color, type, spacing,
radius, background motif) plus minimal per-identity flourishes, over one shared rebuilt
structure. Scope per direction: wordmark treatment, app shell, login, labs list — end-to-end
real screens, not mockups — plus a dev-only `/styleguide` route rendering every primitive
(buttons, tables, badges, forms, dialogs, toasts) under the active identity. A switcher toggles
identities live.

**Exit:** the user picks the winner; losing packs are deleted; the winning tokens become the
design system for all later phases.

**Outcome (2026-07-30, four rounds):** **Schematic won** and is the default design system.
Control Room was cut in round 2 (not professional enough) and the survivors converged on a
shared language (ink-blue neutrals, faint 24px line grid, IBM Plex Mono data, 2px radius);
round 3 trialed Indigo (Schematic's bones in a reference-dashboard colorway with a dark
header over a light body), round 4 merged more Blueprint into it, but it was ultimately
dropped. **Blueprint is shelved, not deleted** — the maintainer's aesthetic preference; it
stays a selectable pack for reconsideration after the full rework. The twin-diamond wordmark
(originally Schematic's) is the logo across all identities. The header-chrome tokens
(`--id-header-*`) built for Indigo remain part of the system.

### Phase 2 — information architecture + role-tailored surfaces

- Role-aware dashboard (fleet overview, recent jobs, activity strip from the SSE stream).
- Permission-filtered navigation; administration area (users/groups) rebuilt under the identity.
- Lab detail rebuilt as tabs (Overview / Topology / Nodes / Operations / Access), tabs and
  actions gated per-lab.
- **Connect drawer** per node: web console, the corrected ssh_config snippet, logs tail, copy
  mgmt IP — the consumer's whole world in one place.
- Job center: global operations surface (live elapsed time, per-job detail drawer with request +
  result), superseding the prototype's per-lab card.
- Account page (API keys, SSH keys) restyled; SSH-key flows keep one-time reveal/download.

**Exit:** all step-1 functionality re-covered under the new identity; a consumer, a manager, an
admin, and a viewer each have a coherent path; `pnpm typecheck` + `pnpm build` green; live smoke
against the stack.

**Outcome (2026-07-30): DONE.** Dashboard landed at `/` (user-chosen) with fleet tiles, cross-lab
recent operations, a session-scoped SSE activity feed (module ring buffer — no server history
endpoint), and a permission-gated admin card. Lab detail became routed tabs
(overview/nodes/operations/access) with a role-aware index redirect (`defaultLabTab`); frozen
test-suites + custom-config sit on Operations (user-chosen). The per-node Connect drawer and the
Account page both serve the corrected SSH guidance from `lib/ssh.ts` (ssh_config block /
ProxyCommand — the bare `-J` copy command is gone). Jobs: one shared `JobsTable` powers `/jobs`
and the per-lab history; aggregation was client-side `useQueries` over per-lab keys with polling
only while a running job was visible — *(superseded 2026-07-30: delta 15 landed `GET /jobs`, so
it is one query and partial failure is no longer possible; see the parked list below)*.
New ui primitives: tabs + sheet (zero new npm deps — the radix-ui monolith covers both).

### Phase 3 — topology view (read-only)

- React Flow canvas on the lab's Topology tab: nodes + links parsed **client-side** from the
  stored definition (`yaml`), auto-laid-out (dagre), pan/zoom/minimap.
- Live overlay: node state coloring from the merged live state; netem badges on impaired
  interfaces (from `GET /netem`); per-node quick actions (console, logs, power, connect).
- Topology export (SVG/PNG snapshot) as a documentation artifact.
- Honest limits: link *oper* state is not on the wire today — the overlay is node-state +
  impairments until the backend exposes the netlab-generated link table (parked below).

**Exit:** any deployed example lab (mpls-l3vpn) renders correctly with live state; actions work
from the canvas.

**Outcome (2026-07-30): DONE.** `lib/topology.ts` is a pure best-effort parser over netlab's
link zoo (strings, lists, dicts, interfaces lists, link groups, dict-of-lists; dotted
`defaults.device` handled) with an `unrendered` count the canvas surfaces — never a silent drop;
multi-access links render as LAN hubs, undeclared-but-linked nodes as implicit, and live
containers missing from the definition as unlinked "drifted" nodes. The canvas (React Flow v12 +
dagre, themed via `--xy-*` → identity tokens) wires fixed-geometry device cards center-to-center
with straight edges, seeds dagre positions only on shape/rankdir change (drags survive live
refetches), overlays state dots and netem badges (`useQueries` over running nodes, keys shared
with the Operations netem controls), and reuses NodeConnectDrawer + NodeControls from a selection
panel. Toolbar: auto-layout, LR/TB, PNG export (`html-to-image`, approved). Undeployed labs
render all-not-deployed — topology as documentation. Link oper state remains parked on the
backend link table. *(Unparked 2026-07-30: the link table shipped — see the parked list below —
and the canvas now renders server-derived edges with true link state.)* *(Superseded 2026-07-31:
the Topology **tab** is gone. Overview and Topology were two surfaces over one artifact — the
stored definition — so the canvas became Overview's **Visual** view via
`components/lab/definition-view.tsx`, carrying the same Visual/Text selector the Build tab uses
(Visual default; both read-only). `/labs/{name}/topology` redirects to overview. The canvas
itself is unchanged.)*

### Phase 4 — guided builder

- The same canvas, editable, on the Build tab: device palette ("add node → pick device/image"),
  drag-to-connect links, property forms (name, device, image, modules).
- The builder **emits** netlab YAML into the stored definition; the text editor remains the
  escape hatch and the definition stays the sole source of truth.
- Round-tripping: builder-emitted definitions re-open on the canvas faithfully; arbitrary
  hand-written netlab (its syntax is far richer than any canvas) re-opens **best-effort**, with
  an explicit "this definition uses features the builder can't represent — edit as text" state.
  Never silently drop definition content.
- Device/image list: a curated client-side catalog first; a backend catalog endpoint is parked
  below.

**Exit:** a user can build a small multi-node lab (e.g. 3 × VyOS + linux host) entirely on the
canvas, deploy it, and see it live on the Topology tab.

**Outcome (2026-07-30): DONE.** The **Build tab** (`lab:edit`, between Topology and Nodes) owns
definition editing in two modes; the header's EditDefinitionDialog is gone. **Visual** edits a
`BuildDoc` — `lib/build-doc.ts`, a *strict* typed subset of netlab (nodes, p2p/LAN links, the
proven ospf/bgp/mpls/vrf module set with `bgp.as`/`mpls.ldp`/`mpls.vpn`/vrf-membership, the
curated `lib/device-catalog.ts` with the `netlab show module-support` matrix, and the
server-injected `name`/`addressing.mgmt` keys preserved verbatim). `parseBuildDoc` is a
reason-collecting gate: anything outside the subset flips Visual into the explicit "this
definition uses features the builder can't represent — edit as text" notice listing *every*
reason (with the read-only canvas as best-effort preview) — content is never silently dropped.
`emitBuildDoc` is canonical and *blocks* Save with named problems (device-less node — device is
intentful; 2-member LAN) instead of silently fixing; round-trip invariant parse(emit(doc)) ==
doc verified against the example, the live stored definition, and eleven gate-trip fixtures.
The canvas derives purely from the reducer's doc (drag-to-connect through a shared
`validateConnect`, palette adds at the viewport center, index-safe multi-deletions), shares the
Topology tab's per-lab layout store (renames migrate the saved position), and the inspector is
where the guidance lives: device Select with inherit-from-default, module checkboxes greyed by
the device matrix, `mpls.vpn` unlocked only when the node's effective modules cover
mpls+bgp+vrf, vrf membership with the customer-loopback flag, name validation that calls out
the hyphen/link-form hazard as you type. **Text** mode is the full-syntax escape hatch.
`netlab_invalid` failures render the envelope's `extras.stderr` in a dismissible panel
(`ApiError` now carries extras); dirty state gets a router blocker + beforeunload +
mode-switch confirms; server-side changes re-sync only while clean. Exit criterion verified
live: the 3×VyOS + linux triangle emitted by the builder deployed to 4 running nodes.

### Phase 5 — editor + polish

- Definition editor upgrade: CodeMirror 6 with YAML highlighting; `netlab_invalid` envelope
  `extras` rendered as inline diagnostics instead of a toast dump.
- Command palette (`cmdk`): jump-to-lab, run actions, keyboard-first navigation.
- Empty states that teach (a fresh `created` lab guides author → deploy; doubles as onboarding).
- Accessibility pass (focus order, contrast under both themes, keyboard reachability), error-UX
  sweep, favicon/meta/branding finish.

**Exit:** frontend step 2 done. **Ordering settled 2026-07-30:** the parked backend items below
come FIRST; the v1.0 release train (publish `twinlab-client` to PyPI, tag) goes LAST, after they
land — v1.0 is marked done only then.

**Outcome (2026-07-30): DONE.** A shared **`CodeEditor`** (hand-rolled CodeMirror 6 wrapper —
controlled value with an echo guard, compartments, `minimalSetup` + explicit extensions, themed
entirely from identity CSS variables so it tracks theme/identity switches live; three new
pack-overridable `--id-code-*` syntax tokens) serves the Build tab's text mode (**yaml + lint
gutter** from client-side `parseDocument` — offsets map straight onto Diagnostics; Save stays
enabled because the server's dry `netlab create` remains the real validator), the Overview
definition card (read-only yaml), and custom-config (read-only jinja2 sources; the templates
dialog is a linted **json** editor). netlab stderr stayed an honest panel — it carries no
positions, so pretending gutter diagnostics would lie. **Command palette** (cmdk, Ctrl/Cmd+K +
header trigger, deferring to an open xterm): page nav gated like the nav bar, current-lab tab
jumps gated per-lab, fuzzy jump-to-lab (the index redirect keeps role-aware landing), Create lab
via a new `/labs?new=1` search param, theme, sign out (shared `useLogout`); lifecycle verbs
deliberately excluded. **Teaching empty states**: builder-canvas overlay, created-lab
getting-started steps on Overview, dashboard create-CTA, jobs-table context line. **Error UX**:
router default error + not-found pages; lab-access failures no longer masquerade as "No grants
yet"; the cross-lab jobs aggregate renders partial data with a failed-labs warning (isError =
all-failed) and Retry affordances landed on the jobs/labs surfaces. **A11y**: aria-labels beside
every icon-only button title, keyboard-operable job rows, login h1, labeled canvas regions.
**Branding**: TwinGlyph SVG favicon (prefers-color-scheme aware), meta description +
theme-colors, `useDocumentTitle` per page. **Contrast audit** (computed, both identities × both
modes): two Schematic-light failures fixed — `--primary`/`--ring` L 0.7→0.64 (3:1 non-text) and
`--id-code-key` pulled 30% toward ink (4.5:1 text); all other pairs passed.

## Non-goals (this rework)

- Mobile-first layouts (responsive-reasonable, not designed-for).
- i18n.
- Any new test-suites UX (frozen pending the backend rework).
- Any macOS/arm64 accommodation (per CLAUDE.md).

## Parked backend / whole-project items (detailed when we get there)

User-stated, for after the frontend work:

- **Test-suites rework** — the suite mechanism itself is changing; frontend follows.
- **Definition input methods** — full-network templates, single-node templates, full network
  from config files, single node from config file, … **Part one DONE 2026-08-04 (contract
  delta 21, APPROVED)**: the template library — `/templates/network` (builtin tier = packaged
  `examples/` mirrors; user tier = labs published live via `PUT /labs/{name}/template`) and
  `/templates/node` (snapshot fragments), gated by the new global-only `template:manage`.
  Frontend: create-lab "Start from" selector, node templates in the builder's Add menu
  (stamped through `parseNodeFragment`), "Save as template" in the node inspector, and the
  lab header's publish-toggle dialog + `template` badge. **Config-file import (part two) DONE
  2026-08-04 (contract deltas 22 + 23)** — record in `docs/config-import.md`. Frontend: the
  `/labs/import` three-step wizard (sources with per-file device select → WIRING, prefilled
  from the server's suggestion and edited by the user, since delta 23 removed inferred
  adjacency → review: warnings,
  renames, inferred definition, per-node interface maps + collapsible carry + quarantine with
  reason badges → create composes createLab → putCustomConfig → updateLabDefinition — custom
  config FIRST, the PUT validates `config:` refs against the stored fileset), an Import button
  on the labs page, and the builder Add menu's "From config file…" (stamps the fragment via
  the shared `stampFragment` path; carry + quarantine land in custom config UNATTACHED with a
  toast explaining the wire-links-first QUIRK — a single config infers no links, so its carry
  keeps SOURCE interface names).
- **Scenario definition** — specific/random traffic between nodes or between "clients" attached
  to edge nodes; specific/random impairment schedules on the network.

Frontend-driven wants that surfaced in this roadmap:

- **Device/image catalog endpoint** — **DONE 2026-08-03 (contract delta 18, APPROVED)**.
  `GET /catalog` serves the curated supported-device set (the tested platforms + linux host;
  policy lives in `backend/services/device_catalog.py`, widening it is the NOS sweep's job) with
  per-device netlab module support under the clab provider and the default clab image — both
  mirrored from the installed netlab with drift-guard tests (the kmods pattern; the module rule
  is provider-aware: linux's libvirt-only dhcp does NOT count) — plus best-effort image presence:
  the runner (the Docker-socket holder) gained a dumb `GET /images` repo:tag listing, and the
  backend owns the matching (untagged defaults normalize to `:latest`). Runner unreachable →
  every `image_present` null behind `live=false`, never an error. Frontend: the builder's
  hardcoded list became `use-device-catalog.ts` over the server catalog (modules intersected with
  `BUILDER_MODULES`, static fallback until the query settles), the Build tab waits for the
  catalog so `parseBuildDoc`'s (now parameterized) known-device gate and the palette agree on one
  list per mount, and the palette + node inspector flag a missing default image.
- **Cross-lab jobs endpoint** — **DONE 2026-07-30 (contract delta 15, APPROVED)**.
  `GET /jobs?limit=` (1-200, default 20) serves recent jobs over every readable lab in one
  indexed query, filtered by the events stream's readable-lab set — any authenticated user, and
  no lab is named so there is nothing to hide behind. Jobs of REMOVED labs are EXCLUDED, the
  approved trade-off: the fleet list follows `GET /labs` and a revived name keeps its empty
  history, while a destroy-with-remove job is still followed by id on its own lab route (which
  stays readable on a removed lab). The frontend's `useAllJobs` fan-out collapsed to one query,
  which removed partial-failure handling (`failedLabs`) entirely.
- **Link table + link oper state** — **DONE 2026-07-30 (contract delta 14, APPROVED)**. `GET
  /labs/{name}/links` serves the LOGICAL link table from netlab's *expanded* topology (`netlab
  create -o config -o provider -o json:nodefault=` — `-o` replaces the default output set and
  `config` must come first or the clab provider's bind validation fails), persisted as a
  regenerable JSONB cache on the lab record by the same dry create that validates a PUT (deploy
  refreshes it; the GET lazily backfills pre-feature rows). Each endpoint carries the
  container-side interface name (netlab `clab.name`-else-`ifname`, live-resolved by
  name-OR-alias against `/interfaces` — cisco IOL's `Ethernet0/1` is the netns `eth1`'s alias),
  netlab IPs (the only IP surface; `/interfaces` is L2-only), live `state`, and the ACTIVE netem
  impairment (orthogonal to state on purpose). Derived `oper_state` is pinned
  (up/degraded/down/unknown); `live` is the honesty flag; 409 `no_definition` on a bare record.
  Implementation finding: clab-api serializes netem per lab (concurrent shows 409 "busy") — the
  impairment merge runs sequentially. All three consumers landed: the **Links card** on the
  Nodes tab (definition-gated, not deploy-gated), **server-driven canvas edges** (stable
  `link:<linkindex>` ids, endpoint-count decides edge-vs-hub — netlab's `type` is NOT a
  rendering signal, a linux-host p2p reads "lan" — with oper-state strokes + animated impaired
  edges and an edge patch path; client parse stays the fallback), and **edge-click netem** (link
  panel with per-endpoint state + extracted `NetemForm`/`useSetNetem`/filtered
  `CurrentImpairments`). Blackbox: the netem test now takes its interface from `links()` instead
  of guessing "first non-mgmt ethN". *(Revised 2026-07-31: impairment is no longer a section
  anywhere — it lives on the row it acts on. The Links table gained an Impairment column
  expanding into `LinkImpairment` (bidirectional; Advanced splits per endpoint), the Interfaces
  card gained a node selector and a per-row single-endpoint `NetemForm` (unidirectional), and
  Operations' netem card is gone — `NetemControls` and `CurrentImpairments` deleted with it.)*
- **SSE job events** — **DONE 2026-07-30 (contract delta 16, APPROVED)**. `GET /events` now
  carries TWO **named** events: `lab` (the container events it always relayed) and `job`
  (`{lab, job_id, kind, status, timestamp}`, emitted at submit and at the terminal state).
  Naming them was the breaking part — every event used to be the unnamed default, so
  `onmessage` sees nothing now; the frontend and the Python client were updated in the same
  batch, and the client SKIPS event names it has no parser for so the server can add more.
  The event is a POKE: no result/error on it, the record stays the record. Job events are born
  in-process, so they ride a deliberately lossy broker (bounded queue per stream, drop rather
  than stall the job runner). There is NO replay on reconnect, so the jobs poll was slowed to a
  15s fallback rather than deleted.
- **Deployed-definition snapshot + server-side topology layout** — **DONE 2026-08-03 (contract
  delta 19)**. The deploy job snapshots the definition it ACTUALLY deployed (captured at job
  start, so a PUT landing mid-deploy can't leak in); `LabDetail` serves `deployed_definition`
  and both wire shapes a derived `definition_drifted` (non-None only while `deployed`; destroy
  clears the snapshot). Drift is exact text equality — and because PUT normalizes the stored
  definition (YAML re-dump while re-pinning name/subnet), comment/formatting edits normalize
  away and never flag: the first live probe (a `# comment` append) proved this by NOT drifting.
  Frontend: a `drifted` badge in the lab header, and the Definition card grew a **Changes** view
  — a dependency-free LCS line diff (`lib/diff.ts`), deployed → stored. The layout half:
  `GET/PUT /labs/{name}/layout` stores ONE shared arrangement per lab (`{canvas-id: {x, y}}`,
  ids opaque to the server, full-replace PUT, `lab:edit`); `topology/layout-store.ts`
  (localStorage) is deleted — `SavedPositions` moved to `topology/flow-types.ts`, the Build tab
  is the ONLY writer (auto-PUT on drag end / rename / palette drop) and the Overview canvas is
  **read/operate-only** (`nodesDraggable={false}`, maintainer's call 2026-08-03): it waits for
  the layout query to settle so the shared arrangement applies on first paint, and re-seeds when
  another user's save changes it (structural sharing keeps identity stable otherwise). The
  canvas's auto-layout button became view-only — it no longer touches the saved arrangement.
- **Builder extras passthrough + first-class groups** — **DONE 2026-08-03** (frontend-only;
  maintainer-directed after the IOL example's `groups:` block hit the strict-subset gate). The
  builder's philosophy changed from "strict subset, gate on everything else" to **typed core +
  lossless extras**: every key lives in exactly ONE of the typed model or a verbatim `extras`
  blob (lab, node, and group level), and ONE shape classifier
  (`labExtrasKeyError`/`nodeExtrasKeyError`/`groupExtrasKeyError` in `lib/build-doc.ts`) is
  shared by the parser and the inspector's new "Advanced properties" YAML editors
  (`build/extras-editor.tsx`) so a key can never end up in both places — typed controls whose
  key the extras own (e.g. a module list carrying `isis`, vrfs with `rd:`) disable with a
  pointer, and the emit guard turns any edge-path same-key collision into a save blocker.
  Groups are first-class: `{name, members, config?, extras?}` with a lab-inspector section
  (member checkboxes, `config` picker fed by the custom-config query — builtins + user
  templates — unknown entries kept as removable chips) and per-node membership toggles; node
  rename/delete keeps memberships consistent; an undeclared member is an emit problem, waived
  for `_auto_create` groups. The structural gate remains for exotic link forms (dict/
  interfaces/link-groups — **the agreed follow-up, parked below**), hyphenated names, and the
  unknown-device POLICY gate. Verified by a 27-check round-trip harness (esbuild bundle under
  node): both MPLS examples + the LIVE stored IOL definition round-trip doc-equal, overflow
  fixtures ride extras, campus-lan gates ONLY on its link forms.
- **Group canvas colors** — **DONE 2026-08-04 (contract delta 20)**. Per-group styling
  (`color`, server-pinned to `#rrggbb`) rides the layout resource — NOT the definition, which
  netlab validates and which stays presentation-free — under the same `GET/PUT
  /labs/{name}/layout` full-replace pair (migration 0018 wrapped the stored shape to
  `{positions, groups}`). Unstyled groups get a deterministic name-hashed pick from the 8-color
  `lib/group-colors.ts` palette, so the server map records explicit choices only. Builder
  canvas: device nodes wear membership dots (one per group, title = name — dots beat a tinted
  border because nodes can be in several groups); inspector group blocks grew a color swatch
  beside the name, a palette row, and a native custom-color input (canvas updates immediately,
  the PUT debounces 400ms since color pickers fire continuously). The Build tab owns the styles
  beside the positions: group rename migrates the entry, delete drops it.
- **Builder link attribute forms** — **DONE 2026-08-04** (frontend-only; batch item 16.3,
  agreed 2026-08-03). The passthrough pattern extended to links: endpoints are
  `{node, extras?}` objects, every link kind carries a typed `name` plus verbatim link-level
  extras, and one-endpoint **stubs** are a third kind (small selectable terminator nodes on the
  canvas, `stub:<n>` session ids; the node inspector adds them). The **dict form** parses —
  declared-node keys are endpoints (netlab's own discrimination rule), their mapping values the
  per-endpoint extras, `name` typed, everything else link extras — and the **interfaces form**
  parses to the same model; emit re-spells it as the equivalent dict form (netlab expands both
  identically — verified live 2026-08-04, incl. a per-endpoint `ifname` override; campus-lan's
  original vs builder-emitted expansion is byte-equal on links AND nodes). Bare links keep the
  terse `a-b`/list spellings; named links wear edge labels. Inspector link/LAN/stub panels: Name
  field + link-level and per-endpoint "Advanced properties" (the LAN-member panel edits that
  endpoint). New emit blockers: a link extras key naming ANY declared node (it would re-parse as
  an endpoint) or shadowing the typed name. Still gated, deliberately: link groups and
  attribute-only entries, the dict-of-lists `links:` shape, a node listed twice on one link
  (self-links), interfaces mixed with node keys, hyphenated names. **campus-lan.yml is fully
  buildable visually** — the 55-check harness pins it plus both MPLS examples, the form
  fixtures, the gates and the blockers.
- **Builder Tier A batch** — **DONE 2026-08-04** (frontend-only; ROADMAP 17.3, scoped off
  `docs/nos-sweep/builder-coverage-gaps.md`). The deliberately-still-gated list above is now
  empty except for what netlab itself rejects: hyphenated names and netlab's real 16-char id
  cap (emit falls back to the list form whenever an endpoint name carries a hyphen, since
  netlab splits the terse `a-b` form on `-`), `nodes:` as a list of mappings, list-form link
  members as `{node, …}` records, the **dict-of-lists `links:`** form kept LOSSLESS through a
  typed `listName` (all-or-nothing, like netlab; a canvas-added link joins the last list and a
  mixed doc is an emit blocker), **link groups** expanded on parse the way expand_groups does,
  **self-links**, netlab's **component include-prefix** endpoints, and **nested groups**.
  Two model changes fell out: endpoints are addressed by POSITION (a self-link's ends share a
  name) across the reducer, inspector and member edge ids, and parse returns `notices` beside
  `reasons` because a save can now legitimately REWRITE a document (a link group comes back
  expanded). Canvas: a self-loop edge (both connect handles sit at the node center, so a
  straight edge would have zero length) excluded from the dagre input, and a read-only
  placeholder node for a component-expanded endpoint that selects its includer.
  Verified by a 36-check round-trip harness, by every definition stored on the running stack,
  and against netlab 26.07: each emitted form creates cleanly and the group expansion is
  byte-identical to netlab's. Live finding recorded in the link inspector: both ends of a
  self-link draw the SAME pool address (netlab derives it from the node id), so netlab
  refuses one unless the link says `prefix: false` or each end carries an `ipv4`.
- **Self password change on the Account page** — **DONE 2026-07-30** (frontend-only; no contract
  change). A Password card heads the Account page with a TanStack Form dialog over
  `PUT /auth/password` (`api.changePassword`): current + new + confirm, zod-validated with the
  server's own 8-character floor and a confirm-match refinement. The current password can only be
  judged by the server, so a **403 `invalid_credentials` renders inline on that field** (cleared on
  retype) instead of as a toast the user has to map back to an input; every other failure goes
  through `toastError`. The change keeps the calling session and revokes the user's others, so it
  ends in a toast saying so — no redirect to `/login`. Wire behavior verified live against the
  stack: wrong current → 403, short new → 422, valid → 204 with the session still authenticated,
  old password refused at login.
