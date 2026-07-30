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

### Phase 5 — editor + polish

- Definition editor upgrade: CodeMirror 6 with YAML highlighting; `netlab_invalid` envelope
  `extras` rendered as inline diagnostics instead of a toast dump.
- Command palette (`cmdk`): jump-to-lab, run actions, keyboard-first navigation.
- Empty states that teach (a fresh `created` lab guides author → deploy; doubles as onboarding).
- Accessibility pass (focus order, contrast under both themes, keyboard reachability), error-UX
  sweep, favicon/meta/branding finish.

**Exit:** frontend step 2 done → v1.0 release train (publish `twinlab-client` to PyPI, tag).

## Non-goals (this rework)

- Mobile-first layouts (responsive-reasonable, not designed-for).
- i18n.
- Any new test-suites UX (frozen pending the backend rework).
- Any macOS/arm64 accommodation (per CLAUDE.md).

## Parked backend / whole-project items (detailed when we get there)

User-stated, for after the frontend work:

- **Test-suites rework** — the suite mechanism itself is changing; frontend follows.
- **Definition input methods** — full-network templates, single-node templates, full network
  from config files, single node from config file, …
- **Scenario definition** — specific/random traffic between nodes or between "clients" attached
  to edge nodes; specific/random impairment schedules on the network.

Frontend-driven wants that surfaced in this roadmap:

- **Device/image catalog endpoint** — what devices/images can this deployment actually run
  (feeds the builder palette; replaces the curated client-side list).
- **Link table + link oper state** — expose the netlab-generated link graph and per-link state
  (upgrades the topology overlay from node-state-only to true link state).
- **SSE job events** — already in ROADMAP; would let the job center drop its polling.
- **Deployed-definition snapshot** — enables "definition drifted since deploy" hints.
