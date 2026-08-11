# Twinlab Integration Roadmap

Planned integrations for deeper control and observability of running labs, drawing
on the `clab-api-server` v0.5.0 surface and `netlab`. This file is the durable
record of the agreed sequence, the grounded API facts behind it, and the
decisions already locked — so the plan survives context loss and implementation
doesn't need to re-research the endpoints.

Status legend: **done** (shipped) · **in progress** · **planned** (agreed, not
started) · **deferred** (explicitly parked) · **candidate** (proposed, not yet
decided).

## Road to v1.0 — the whole remainder, in order

Everything else in this file is either shipped or explicitly post-tag. Kept here
because the remainder had grown scattered across four items and no single place
said what was left.

1. ~~**`tc:` baseline impairment — gap 1 / contract delta 25**~~ — **DONE
   2026-08-05 by REJECTING it** (item 17.2). Re-analyzed at the end of item 17 as
   the deferral asked. The honor-it sketch is withdrawn: the knob mapping was
   never the hard part (probed — `tc.rate` is bit/s to our netem's kbit/s, the
   rest is exact), but honoring `tc:` forces the baseline-vs-runtime design, and
   its "clear reverts to baseline" rule would change delta 7's shipped REPLACE
   semantics for a key with no demand behind it. So `tc:` joins `tools:` and the
   up/down hooks as 422 `unsupported_directive` at PUT — never silent — and the
   netem API stays the one way to shape a lab. **This closes item 17 entirely.**
2. ~~**Tier B builder promotions**~~ — **DONE 2026-08-05**, reviewed in
   `docs/nos-sweep/builder-coverage-gaps.md` §6 and shipped as six frontend
   commits. Scoped by three findings rather than by size: one unknown module
   emptied the protocol UI, config import produced labs that were 100 % extras,
   and one of our own examples used two extras keys. The exclusion list was sent
   back once and re-derived from netlab's own behaviour — "no demand" read off
   our repo is one maintainer's usage, not evidence — which moved node
   `cpu`/`memory` out (libvirt-only, inert under clab) and `box`/`role`/`group`
   in.
3. ~~**Pin the fact-namespace subset**~~ — **DONE 2026-08-05 (contract delta 26,
   APPROVED and SHIPPED same day)**, closing delta 17's pre-v1.0 reservation.
   A promised core plus a per-object **`_extras`** holding every unpinned key —
   internal keys included, nothing dropped, no promises inside `_extras`, the
   tier visible in the template path. Analysis, evidence (14 nodes across all
   six platforms) and live verification in `docs/fact-namespace.md`; the
   member lists are a contract appendix and a drift-guard test over the
   examples' real netlab output is their teeth.
4. ~~**Playwright e2e UX suite** (item 14)~~ — **DONE 2026-08-06**: the `e2e/`
   project (see item 14 below), 51 specs green from a pristine stack reset in
   ~5 minutes, and four real bugs found and fixed on the way (mgmt-subnet pins
   in served templates, two clab-api concurrency classes, and the
   /run/netns mount-propagation break of node stop).
5. ~~**The two name findings item 14 surfaced but left open**~~ — **DONE
   2026-08-06**, both the same class: a name Twinlab accepted that netlab's
   `must_be_id` rule (a leading letter or underscore, then
   letters/digits/dash/underscore, 16 characters) cannot carry. (a) `POST /labs`
   took the wide `_Name` (64 characters, dots, a leading digit), so a name past
   the rule created a live record — mgmt subnet reserved — whose definition PUT
   could never succeed; create now gates on netlab's rule intersected with
   docker's object-name rule (leading LETTER, since the name prefixes the lab's
   containers and networks), mirrored in the create dialog and the import
   wizard, which had no validation at all. (b) config import rewrote hyphens to
   underscores (`core-r1` → `core_r1`) although netlab accepts them — a twin
   that no longer answers to the name the operator knows the box by. It now
   renames only what netlab refuses (dots, a non-letter start) and truncates at
   the 16-character cap it never enforced, so an over-long hostname stopped
   producing a `netlab_invalid` import; truncation collisions surface as
   `duplicate_node` naming the cap and the per-source `name` override.
6. ~~**Custom-config templates as scoped records — contract delta 27**~~ — **DONE
   2026-08-07**, design record `docs/custom-config-templates.md`. Not on this
   list when it was written: it opened as a complaint that the builder's picker
   "offers them on every lab", and the discussion found that to be one symptom
   of the storage model rather than a UI bug. A raw `{relpath: content}`
   fileset made the PATH do double duty as storage key and entire metadata
   model — name, tier and device scope all spelled into one string and
   re-derived, badly, by every consumer. A template is now a `{name,
   description, tier, variants}` record whose node/device/universal scopes
   mirror netlab's own `first_found` precedence; the netlab-facing fileset is
   MATERIALIZED at the config-push boundary and never stored; and applicability
   is ONE rule driving the picker's greyed-with-reason offers, so `mpls_te` on
   a VyOS lab stopped being an attachable mistake that failed two steps later
   in netlab's voice. Migration 0020 reshapes stored rows exactly and fails
   loudly on an unmappable path. Remodelled now precisely because the contract
   still has no external consumers — after the tag it would have been a
   breaking change.
7. ~~**Test-command language + honest `interactive` — contract delta 28**~~ —
   **DONE 2026-08-10**, design record `docs/validation-transport.md`. Also not
   on this list: found by running the SHIPPED mpls-l3vpn suite against a live
   lab, where a VRF ping written in VyOS op-mode silently reached Linux's
   `/bin/ping` (no `vrf` flag, empty stdout, no explanation). The exec
   transport lands in the CONTAINER'S SHELL, not the NOS CLI, and nothing in
   the contract had ever said which interpreter a `command` is for.
   `TestCase.mode` (`shell` default | `cli`) names it, `services/cli_adapters.py`
   rewrites per device and absorbs config-diff's hard-coded wrapper, and
   `TestResult.command` reports what actually ran. `interactive: true` — a
   SILENT no-op on docker nodes — is now a PTY-backed `docker exec -it`.
   Admitting a platform gained a SIXTH coordinated change (its `CLI_ENTRIES`
   entry). A per-test TRANSPORT selector (exec vs ssh) was considered and
   DEFERRED: op-mode comes from interactive shell INITIALIZATION, so one-shot
   SSH would have had the identical bug — switching transports was never the
   fix.
8. ~~**The job step log — contract delta 29**~~ — **DONE 2026-08-10**, design
   record `docs/job-steps.md`. Opened as a UX complaint with a backend cause: a
   deploy showed its progress in a modal, and leaving the modal lost it while
   the job carried on as an opaque "running" row whose drawer only echoed the
   request back. The events behind that modal were never the interesting part —
   every phase that decides whether a deploy is HEALTHY (the image pre-flight,
   host prep, netlab's output, Ansible's per-node push, the config-time gate)
   runs inside the job task and never left the backend, which is why the dialog
   had to apologise in prose for its own quiet stretches. So the operation now
   RECORDS what it did: `{at, code, level, message}` steps appended to the job
   row as they happen, served on the single-job read as `JobDetail`, durable
   after the job ends. A narrative, never the record — nothing is derivable
   only from a step, so the vocabulary may grow without a contract change. One
   frontend component renders steps over the session's container events, and
   both the deploy dialog and the jobs drawer use it. Considered and PARKED:
   capturing clab-api's container events server-side per job (an SSE fan-out
   refactor — the backend opens one upstream stream per browser today, so with
   nobody watching nothing is recorded); and streaming netlab's and Ansible's
   raw output, which is a transcript, a different feature with its own
   retention questions.
9. **The release train** (item 22). Publish `twinlab-client` to PyPI, tag v1.0.
   **LAST**; item 14 and its findings are done, so this is the whole remainder.
   Its pre-flight ran green 2026-08-06 but is **stale** — deltas 27, 28 and 29,
   the VyOS image pin and the shielded session close have landed since, so it
   must be re-run.

Explicitly NOT in v1.0: the CML licensing revisit (item 20), the acquisition-blocked
platform tail (item 21), validation-gate parallelization (item 10), packet capture +
metrics (Phase 6), i18n, and the 2026-07-23 API-review deferrals at the end of this
file.

## Locked decisions

- **Phase 6 (packet capture + metrics stack) is deferred** — "to be defined
  later". Do not start without an explicit go-ahead and a scope decision (see the
  open question under Phase 6).
- **Whole-lab freeze is per-node fan-out, non-atomic.** clab-api v0.5.0 has no
  whole-lab pause endpoint. "Pause the network" iterates `pause` over each node;
  we accept that it is not atomic.
- Phases are shippable in order; cheap-and-foundational precedes
  expensive-and-flashy; nothing blocks on the two heaviest items.

## Grounded facts (verified against clab-api-server v0.5.0 source + netlab docs)

All clab-api paths are under `/api/v1`, JWT-authenticated (`Authorization:
Bearer <token>`). Sources: `internal/api/routes.go`, `internal/models/models.go`,
`docs/swagger.json` at tag `v0.5.0`; netlab.tools docs.

- **Node mgmt IP** is already in the inspect/list response as `ipv4_address`
  (CIDR, e.g. `192.168.121.101/24`) and `ipv6_address`. Our `_ClabNode` parser
  currently drops it. The `/interfaces` endpoint is L2-only (no IPs). There is no
  server-provided ready-made `ssh user@mgmt-ip` string for the direct path — we
  build it from `ipv4_address` (strip the `/NN`).
- **Pause/unpause**: `POST .../labs/{lab}/nodes/{node}/{pause|unpause}`. Per-node
  only; no `/labs/{lab}/pause`.
- **Events**: `GET /api/v1/events` streams containerlab events as **NDJSON**
  (line-delimited JSON over a long-lived HTTP response) — *not* SSE, *not* a
  WebSocket. Also `GET .../labs/{lab}/topology/events` and
  `.../labs/workspace/events`; node logs can stream with `?follow=true`.
- **Netem**: `POST /api/v1/tools/netem/set` (body: `ContainerName`, `Interface`,
  `Delay`, `Jitter`, `Loss` %, `Rate` kbit, `Corruption` %),
  `GET /api/v1/tools/netem/show`, `POST /api/v1/tools/netem/reset`. Keyed by
  **container + interface**, not by link.
- **Web terminal**: native WebSocket, no external tool. `POST
  .../labs/{lab}/nodes/{node}/terminal-sessions` (body `protocol` ssh|shell|
  telnet, `cols`, `rows`) → `sessionId`; `GET
  /api/v1/terminal-sessions/{id}/stream` upgrades to a **WebSocket** (client sends
  `{type: input|resize|close}`, server streams base64 `{type: output}` +
  `ready`/`exit`); `DELETE /api/v1/terminal-sessions/{id}` ends it. (A separate
  `POST .../nodes/{node}/ssh` port-forward proxy also exists, returning a
  `Command` string, if we prefer external ssh over an in-browser terminal.)
- **Capture** (Phase 5): `POST .../labs/{lab}/capture/packetflix` (Edgeshark URI
  for local Wireshark) or `.../capture/wireshark-vnc-sessions` (Wireshark-in-a-
  container over noVNC, proxied by the API). No raw `.pcap` download.
- **Metrics** (Phase 5): clab-api does **not** serve per-node or Prometheus
  metrics. `GET /api/v1/health/metrics` is the API server's *own* CPU/mem as JSON.
  A real per-node metrics stack is a separate build.
- **netlab mgmt subnet**: defaults to `192.168.121.0/24` (first host
  `.101`, start offset 100). Override per lab via the `addressing.mgmt` pool:
  `addressing.mgmt.ipv4` sets the subnet; also set `addressing.mgmt._network`
  (and/or `_bridge`) so concurrent labs don't collide on one shared Docker mgmt
  bridge.
- **`netlab up` dependence**: only `netlab status` truly needs a full `netlab up`
  (it writes `~/.netlab/status.yml`). `connect`, `exec`, `collect`, `validate`,
  `down` read the **snapshot + Ansible inventory** that plain `netlab create`
  already produces — so they are mechanically reachable on our create/deploy/
  initial split *if* the snapshot's names/IPs/ports match the running lab (not
  officially supported by netlab against a lab it didn't deploy).

## Phases

### Phase 0 — cheap wins on existing plumbing · **done**
First commit(s); small and independent.

1. **SSH mgmt details in the UI.** Parse `ipv4_address` in `_ClabNode`, thread it
   into `NodeInfo` → `LabNodeState` → the frontend node row; render a
   copy-pasteable `ssh <user>@<mgmt-ip>` command. Note in the UI that it runs from
   the **host** (nodes sit on the host mgmt bridge; the compose services can't
   reach it directly). Default VyOS creds `vyos`/`vyos` unless the definition
   overrides.
2. **Pause / unpause.** Add `pause`/`unpause` to the node-action path (mirrors the
   existing start/stop/restart plumbing in `services/clab_api.py` +
   `api/labs.py` + the frontend node-controls menu). Whole-lab "freeze" =
   client-side fan-out over nodes (non-atomic, per the locked decision), surfaced
   as a lab-level control alongside start/stop/restart.

### Phase 1 — foundational backend · **done**
3. **Per-lab mgmt subnet + concurrency.** Inject a distinct `addressing.mgmt.ipv4`
   (and `_network`) into each lab's definition — same mechanism as `set_lab_name`
   in `services/netlab.py`. Needs a subnet allocator that tracks used /24s
   (persist in the `labs` table) and picks a free one. Backend-only, no UI. This
   is what makes running several labs at once actually work, and it makes the
   Phase 0 SSH IPs correct per lab.

### Phase 1.1 — concurrency hardening · **done**
A live concurrent-deploy test (two labs at once) surfaced three races that the
subnet mechanism alone didn't cover; all fixed and re-verified (two simultaneous
configured labs → distinct subnets, both configured, both SSH-able):
- **Subnet allocation TOCTOU.** The subnet was persisted only *after* the slow
  deploy, so simultaneous deploys allocated the same /24. Fixed by reserving the
  lab row (status `deploying`) with its subnet *before* deploy, a `UNIQUE` index
  on `labs.mgmt_subnet` (migration 0004), and retry-on-conflict for auto-allocated
  subnets. Deploy failure releases the reservation.
- **`netlab create` `~/.netlab` race (backend).** Two creates raced to first-make
  the shared status dir. Fixed by pointing `HOME` at the per-call tempdir (backend
  only runs `netlab create`, no Ansible).
- **Config-push `~/.netlab` race (runner).** Same shared state, but the runner's
  `netlab initial` needs the real `~/.ansible` (the `community.docker` connection
  plugin), so HOME can't be isolated — instead config pushes are **serialized**
  with an `asyncio.Lock` (one lab configures at a time; deploys stay concurrent).

**~~TODO~~ CLOSED by the async job model (2026-07-29).** A backend crash mid-deploy
used to leave the row stuck in `deploying`. The job model's startup sweep
(`job_store.sweep_orphans`) fails any orphaned `running` job and restores the
lab's pre-deploy status from the deploy job's stashed `_previous_status` — the
subnet stays reserved on the record, as designed.

### Phase 2 — live UI substrate · **done**
4. **Live events.** Backend consumes the clab-api `GET /api/v1/events` NDJSON
   stream and re-exposes it as **SSE** at `GET /api/v1/events`, distilled to a lean
   `{lab, node, action, timestamp}` (`lab` from the event's `containerlab`
   attribute). Auth is resolved up front and its DB session released before the
   long-lived stream (so an open connection doesn't pin a DB connection); `lab:read`
   gates it; one upstream clab-api stream per browser connection; keepalive comments
   while idle. Frontend `useLabEvents` (mounted in `AppShell`) opens an
   `EventSource` and debounce-invalidates the `['labs']` query tree on each event —
   deploys/power actions/out-of-band changes now show up without polling. Verified
   live end-to-end through the Vite proxy.

### Phase 3 — testing-twin differentiator · **done**
5. **Netem link impairment.** `tools/netem` set/show/reset, wrapped in the
   clab-api client and exposed per node: `GET/POST .../nodes/{node}/netem` and
   `POST .../nodes/{node}/netem/reset`. The API is keyed by node + interface (as
   everywhere else); the node's container is resolved from live clab-api state,
   since netem is keyed by container, not the short node name the other node
   routes accept. Set/reset take `lab:configure`, show takes `lab:read` (the same
   read-vs-mutate split as logs vs power control). The netem routes are declared
   before the `{action}` node route so the static `netem` segment isn't captured
   by the `NodeAction` path param. Only the impairments the caller set are sent
   (an omitted field is left unchanged, not zeroed); `NetemSetRequest` rejects an
   empty impairment set and jitter without delay. UI: a "Link impairment (netem)"
   card on the lab detail page picks node + interface (from the existing interface
   inventory) and sets delay / jitter / loss / rate / corruption, shows current
   state, and resets — set form gated on `lab:configure`, state table on
   `lab:read`.

### Phase 4 — big interactive lift · **done**
6. **Web terminal.** Proxy clab-api's terminal-session WebSocket through FastAPI
   and drive an xterm.js console on the lab detail page. Native WS end to end; no
   external tool. This is the first WebSocket path in the stack (events are SSE),
   so it introduces a client-side WS library and a WS-aware dev proxy.

**clab-api surface (v0.5.0) — re-verify node identity empirically first (the
naming quirk: some `{node}` segments take the short name, some the container):**
- `POST /api/v1/labs/{lab}/nodes/{node}/terminal-sessions` (JSON `{protocol:
  ssh|shell|telnet, cols, rows}`) → `{sessionId}`. Plain authenticated HTTP —
  reuses the existing `_authed` httpx path.
- `GET /api/v1/terminal-sessions/{id}/stream` — **WebSocket upgrade**,
  `Authorization: Bearer <jwt>` on the handshake. Client→server text JSON
  `{type: input, data}` / `{type: resize, cols, rows}` / `{type: close}`;
  server→client `{type: ready}`, `{type: output, data: <base64>}`, `{type: exit}`.
- `DELETE /api/v1/terminal-sessions/{id}` — end the session.

**Backend — new `api/terminal.py` WS endpoint + client methods:**
- `WS /api/v1/labs/{name}/nodes/{node}/terminal?protocol=ssh&cols=&rows=` on the
  FastAPI side. `protocol` is a query param — `ssh` (default) or `shell`.
- **Auth before accept.** Read the session cookie off the handshake
  (`websocket.cookies`), resolve it in a short-lived DB session, require the new
  `lab:terminal` permission (see below), then release the DB session *before* the
  pump — the same "don't pin a DB connection on a long-lived stream" rule
  `events.py` follows. Reject with `close(code=1008)` on auth/permission failure.
- **New `lab:terminal` permission (locked).** A distinct permission, not a reuse
  of `lab:configure` — terminal access is its own grant. Add the constant to
  `auth/permissions.py`, append it to `ALL_PERMISSIONS`, and wire it into
  `ROLE_DEFINITIONS` (admin gets it via `ALL_PERMISSIONS`; grant it to `operator`;
  `viewer` does **not** get it). `seed_rbac` creates the row and re-wires roles on
  the next startup — **no migration** (permissions are code-defined + re-seeded).
- **Container identity.** Resolve the node's container with the existing
  `_resolve_container` (live inspect); re-verify whether terminal-sessions wants
  the short node name or the container name — do not assume.
- **New `ClabApiClient` methods:** `create_terminal_session(node, protocol, cols,
  rows) -> Result[str, ClabApiError]` and `delete_terminal_session(id)` (both via
  `_authed`), plus `open_terminal_stream(id)` using a **client-side WebSocket
  library** — httpx cannot do client WS. Proposed: `websockets` (BSD-3,
  OSI/Apache-2.0-compatible; already present transitively via
  `uvicorn[standard]`), promoted to a direct dep with `uv add websockets`.
  **Needs approval before adding.**
- **Relay loop.** Create the upstream session (HTTP), open the upstream WS with
  the JWT, then pump both directions as **transparent JSON text frames** — the
  browser speaks clab-api's terminal protocol directly, so the proxy neither
  parses nor base64-decodes payloads (kept dumb: auth + relay + lifecycle only).
  Two tasks (browser→upstream, upstream→browser); the first to finish tears the
  other down. On every exit path, best-effort `DELETE` the session and close both
  sockets.

**Frontend — xterm.js console:**
- Add `@xterm/xterm` + `@xterm/addon-fit` (MIT). **Needs approval before adding.**
- A per-node "Console" control (button in `node-controls.tsx` opening a dialog)
  that opens the WS, wires xterm ↔ socket: terminal `onData` → `{type:input}`,
  fit-addon resize → `{type:resize}`, incoming `{type:output}` →
  `term.write(atob(data))`, `{type:exit}` → "session ended". A protocol toggle
  (ssh / shell) sets the query param, default `ssh`. Gated on `lab:terminal`;
  shown only while the node is running.
- **Vite proxy must forward WS:** add `ws: true` to the `/api/v1` proxy entry in
  `vite.config.ts` — http-proxy does not upgrade WebSockets otherwise.

**Locked decisions:**
- **Permission:** a new `lab:terminal` permission (granted to admin + operator, not
  viewer); code-defined + re-seeded, no migration.
- **Protocol:** `ssh` and `shell` offered as separate options, **`ssh` prioritized**
  (default). `telnet` deferred.
- **Deps (approved):** `websockets` (backend, BSD-3) via `uv add websockets`;
  `@xterm/xterm` + `@xterm/addon-fit` (frontend, MIT) via `pnpm add`.

**Testing.** Unit-test the client methods (create/delete over mocked httpx) and
the auth-before-accept gate; the relay itself is integration-tested live (open a
console into a running vyos node, run a command, resize, confirm the session is
deleted on close). No `-x`; full output to a temp file.

### Phase 5 — validate before prod · **done**
7. **Test suites (own runner, in the backend).** Declarative assertions run against
   the live lab, surfaced pass/fail per test. Strong fit for the "validate before
   prod" testing mission. **We build our own runner rather than wrapping `netlab
   validate`** — see the research and rationale below.

**Implemented (2026-07-21).** All of the design below shipped: the `lab:validate`
permission, a clab-api `exec` client method, the validation runner + safe matcher
(`services/validation.py`), the `test_suites`/`last_validation`/`config_time_ok`
columns (migration 0005), the GET/PUT/run test-suite endpoints, config-time gating
wired into deploy/redeploy/configure behind `skip_config_time_checks` (a failure
sets `config_time_ok=false` and returns status `validation_failed`, lab stays
deployed), and the frontend Test Suites panel (view/run/JSON-author) with the
config-time-failed badge and the deploy/redeploy skip options. Backend + frontend
gates green (70 backend tests). **Deferred (noted for later):** device-keyed
per-test commands (v1 is a single command string), the netlab-style expression
matcher, and a config-time status column in the labs *list* table (the detail-page
badge already marks a failed config). **Two of those three have since shipped and
this whole phase is SUPERSEDED by item 15** (test-suites v2, contract delta 17):
device-keyed `TestCase`s are the v2 model, and `config_time_status` rides both the
list and the detail payload. Only the netlab-style expression matcher is still
deferred — and v2's `compare` grammar over parsed data covers most of what it was
wanted for. The text below is the as-built record of v1, kept for its research and
rationale.

**Research (verified against netlab 26.06 + netlab's published integration tests):**
- netlab's semantic validation plugins (`plugin: ospf_neighbor(...)`, `bgp_*`,
  `route_*`) exist **only for `eos` + `frr`** (ospf/bgp) and **`frr`** (isis/route).
  A plugin is resolved purely by a `{device}.py` file on the `defaults.paths.validate`
  search path; there is **no `vyos.py` and no vyos→frr alias** in netlab, nor in any
  device's settings. So on VyOS — our verified reference — every semantic check
  **SKIPs** ("Cannot find validation plugin for device vyos"). Cisco is the same:
  no plugin, and not FRR underneath, so no shim helps it either.
- How netlab itself validates VyOS: it does **not** run semantic checks on the box.
  Its OSPF integration test puts **FRR "probe" nodes adjacent to the DUT** and runs
  the semantic plugin *on the probes* (`nodes: [x1, x2]`, both `frr`), checking the
  DUT from a neighbor's viewpoint. Published VyOS results: OSPF 23 passed/1 caveat,
  BGP + IS-IS pass — all via FRR probes. That works but injects validation-only
  nodes into the topology, which conflicts with "the definition is the user's
  intent". A lab author may add a probe themselves; we won't do it automatically.
- The only mechanism that works **uniformly across every device netlab supports**
  (VyOS, Cisco, anything) is the **generic command + match** form. That, plus
  Twinlab's device-agnostic principle, is why the generic form is our foundation.
- **Importing netlab's parser functions was evaluated and rejected.** The
  convergence checks we want are ~10 trivial lines each; netlab's real depth (BGP
  communities/AS-path/cluster-id/MED) is out of scope and FRR-schema-specific. The
  functions aren't clean library calls — they signal via raised netlab exceptions
  (`log.Result`/`log.Skipped`), read `global_vars` global state, and pull in
  `box`/`netsim.*`; using them means adopting netlab's harness and coupling to its
  private API (26.06). It's also MIT code that would force validation into the
  runner/ansible zone. Building our own keeps it in the **Apache-2.0 backend**,
  unlinked, over **clab-api `exec`** (the endpoint the container-name `nodeFilter`
  already targets) — no netlab, no runner, no license question.

**Model — test suites.** A lab record holds a `test_suites` field (never sent to
`netlab create`, so it can't trip netlab's strict attribute validation). Each named
suite carries a `stage` and a list of tests:

```yaml
test_suites:
  convergence:                     # suite name
    stage: config-time             # auto-runs after configure; gates "config done"
    description: Declared protocols converge before we trust the lab
    tests:
      ospf_adj:
        nodes: [r1, r2]
        command: 'show ip ospf neighbor'   # string, or device-keyed {vyos:..., frr:...}
        expect: { contains: Full }         # contains | not_contains | matches (regex) | json
        wait: 40                           # poll until pass or timeout (seconds)
  post_acl_tighten:                # a runtime suite
    stage: runtime
    description: Verify the new ACL blocks what it should
    tests:
      blocked:
        nodes: [r1]
        command: 'ping -c1 10.0.0.9'
        expect: { not_contains: '1 packets received' }
```

- **`stage` controls only *automatic* execution.** `config-time` = "also run
  automatically at the end of a configure"; `runtime` = manual only. **Manual runs
  work on any suite** regardless of stage — so `convergence` can be re-run on demand,
  and "change config → validate X, change other config → validate Y" is just runtime
  suites triggered after each change.
- **Multiple config-time suites** are allowed; all run and all must pass.
- **Match primitive is safe by construction** — `contains` / `not_contains` /
  `matches` (regex) / `json` (path-equals over `... json` output). **No arbitrary
  expression `eval`.** *(Future: a netlab-style expression form is noted as a
  possible later addition, deliberately deferred — start safe.)*

**Config-time validation (the "validate before prod" gate).** The configure flow
becomes deploy → `netlab initial` → run all `config-time` suites (with per-test
`wait` polling) → declare config done only if they pass.
- **Skip flag:** `skip_config_time_checks: true` on the deploy/configure call
  bypasses them (default `false`, so convergence gating is on by default).
- **On failure the lab stays deployed but is clearly marked failed.** No rollback —
  it's a sandbox; you want to inspect a lab that failed to converge. The record
  carries an explicit config-time-validation-failed signal (persisted result +
  a distinct flag/status surfaced in list/get and the UI), so a failed config is
  unambiguous, not silently "deployed".

**Backend API (`/api/v1`, existing lab-route conventions; all in the backend over
clab-api `exec`):**
- `GET /labs/{name}/test-suites` — suites with stage, test count, last-run summary
  each. `lab:read`.
- `PUT /labs/{name}/test-suites` — replace the suite set (schema-validated on write).
  `lab:create` (same grant as editing the definition).
- `POST /labs/{name}/test-suites/{suite}/run` — run one suite on demand (any stage);
  returns the typed report. **New `lab:validate` permission** (admin + operator, not
  viewer; code-defined + re-seeded, no migration — same pattern as `lab:terminal`).
- `POST /labs`, `/redeploy`, `/configure` gain **`skip_config_time_checks: true`**
  (default `false`). When `configure` runs and the flag is unset, all `config-time`
  suites run as the final step; their aggregate report is in the response and
  persisted. The **automatic** config-time run rides the existing `lab:configure`.
- **Report shape (per run):** `{ suite, stage, summary: {passed, failed, skipped},
  ran_at, results: [{name, node, status: pass|fail|skip|error, command, output,
  expect, elapsed_ms}] }`.
- **Persistence:** last result **per suite** on the record (status + summary +
  timestamp), plus the config-time-failed flag. One migration.
- **Client:** one new `ClabApiClient.exec(container_name, command) -> Result[...]`
  over clab-api's exec endpoint, plus a pure `evaluate_expectation(output, expect)`
  matcher. Errors-as-values throughout.

**Frontend — a "Test Suites" panel on the lab detail page:**
- Split into **Config-time** and **Runtime** sections. Each suite row: name ·
  description · stage badge · last-run summary ("5/6 passed · 2m ago", colored) ·
  a **Run** button (`lab:validate`) · expandable per-test table (name · node ·
  status badge · command / output / expectation). Config-time suites show their
  result from the most recent configure, with the failed state clearly flagged.
- **Deploy / configure dialog:** the existing "configure" checkbox plus **"Skip
  config-time checks"** (enabled only when configure is checked) → wires
  `skip_config_time_checks`. The post-deploy summary surfaces config-time pass/fail.
- Suites authored via the edit-definition dialog extended with the `test_suites`
  block (a structured editor can come later).

**Locked decisions:**
- **Own runner in the Apache-2.0 backend over clab-api `exec`** — not `netlab
  validate`, no netlab import (rationale above).
- **Config-time failure:** lab stays `deployed`, but the record clearly marks the
  config-time validation as failed (persisted + distinct flag surfaced in API + UI).
- **Match primitive:** safe `contains`/`not_contains`/`matches`/`json` only;
  expression `eval` **noted for later**, not built now.
- **Permission:** new `lab:validate` for manual runs; automatic config-time runs
  ride `lab:configure`.
- **Suites location:** a `test_suites` field on the lab record, **never** passed to
  `netlab create`.

### Phase 6 — heavy / external-dependency · **deferred (TBD later)**
8. **Packet capture** — Edgeshark packetflix or Wireshark-VNC. Needs new infra
   and an **OSI/Apache-2.0-compat licensing pass on Edgeshark** before committing.
9. **Metrics stack** — not served by clab-api; a separate build (e.g.
   Prometheus/Grafana/cAdvisor scraping the lab containers, or lightweight
   per-node CPU/mem/traffic straight from the Docker API). **Open scope question
   to resolve when this is picked up:** full observability stack vs. lightweight
   Docker-API stats.

### Validation-gate parallelization · **deferred** (until gate wall-time warrants it)

10. **Run the config-time gate's checks concurrently.** The gate runs its
    `(test, node)` checks **sequentially** today. That is fine at current scale
    (the `mpls-l3vpn-iol` gate = 26 checks in ~23s over `netlab exec`), so this is
    **parked** — the full design and race analysis are captured here so it doesn't
    need re-deriving when the time comes.

**Trigger to pick this up:** gate wall-time becomes painful — a lab with enough
nodes × checks that sequential execs run into minutes, or a suite where the
sequential **worst case** matters. Today a slow-converging check blocks the rest,
so the worst case is *the sum of every test's `wait`*; parallelizing makes it
*`max(wait)`* instead. (Historical note: an apparent ~8-minute "hang" during the
custom-config work was **not** this — it was a bug where every exec 422'd and each
test polled its full `wait`; fixed. Post-fix the sequential gate is ~23s, hence the
deferral.)

**Where the serialization lives (two layers — both must change):**
- Backend — `run_suite` (`services/validation.py`) is a sequential
  `[await _run_check(...) for test… for node…]`.
- Runner — `app.py`'s `_netlab_lock` (one `asyncio.Lock`) wraps **every** `/exec`,
  so backend concurrency alone would still serialize at the runner.

**Design:**
- Backend: `run_suite` fans out with `asyncio.gather`, bounded by a semaphore
  (~8). Each `_run_check` keeps polling independently.
- Runner: stop holding a global lock across the whole exec. `netlab exec` is a
  **separate subprocess that only reads** shared files, so many can run at once;
  only the writers (`netlab create` / `initial`) stay serialized.

**Verified facts behind the design (checked during the custom-config work):**
- `netlab exec` = `load_snapshot` (read the per-lab pickle) + `connect_to_node`
  (spawn ssh/docker); a separate subprocess, no shared in-process state, read-only
  on shared files. 4 concurrent execs ran in 3s vs 13s sequential, no corruption.
- `netlab exec` loads the snapshot fine under an isolated `HOME` (reaches the SSH
  stage), and netlab already guards stats with `~/.netlab/stats.json.lock`.

**Race conditions + handling:**
- **R1 — cold-cache build stampede.** N parallel execs on a cold inventory cache
  would all `rmtree`+`netlab create` the same `exec-cache/<lab>` dir. → **double-
  checked locking**: fast lockless cache check; on miss take a per-lab lock,
  **re-check** (another thread may have just built it), build only if still cold.
- **R2 — `~/.netlab` reader/writer.** `create`/`initial` (writers) vs `exec`
  (reader) racing on the shared status dir. → **per-lab `HOME=<workdir>`
  isolation** so labs share no `~/.netlab`; `/configure` keeps the *real* HOME (its
  `netlab initial` needs `~/.ansible`), so it is disjoint from exec's HOME.
  *Alternative:* a global reader-writer lock — HOME isolation is preferred (more
  concurrency, no new lock type). **Must verify a VyOS/docker-transport exec still
  works under a changed HOME before trusting the isolation.**
- **R3 — result / DB write.** None needed: `gather` collects, then the endpoint
  does a **single** `record_validation`. No per-check DB write (unchanged).
- **R4 — resource exhaustion.** Cap in-flight execs with the semaphore (~8) to
  protect the host and each node's `sshd MaxStartups`.
- **R5 — poll interaction.** Each `_run_check` polls in its own gathered task;
  concurrency turns the worst case from `sum(wait)` into `max(wait)`.

**Scope when built:** `netlab-runner/runner.py` (double-checked per-lab build lock
+ `HOME=<workdir>` on the cache-build create and on exec), `netlab-runner/app.py`
(drop `_netlab_lock` from `/exec`, keep it for `/configure`),
`backend/services/validation.py` (`run_suite` → bounded `gather`). Tests: runner
concurrency (parallel execs don't corrupt / build exactly once) + backend
`run_suite` issues checks concurrently. **Interacts with** the Phase 1.1
"Config-push `~/.netlab` race (runner)" note — that `asyncio.Lock` stays, guarding
`/configure` only.

### RBAC v2 — scoped roles, groups, owner-delegated grants · **done**

11. **Per-lab authorization, user groups, and delegated grants.** RBAC v1 (shipped)
    is flat and global: a permission is decided without regard to which lab, `owner_id`
    is never consulted, `GET /labs` returns every lab, and there is no way to delegate
    access. v2 makes authorization **scoped** (*does this user hold X on this lab?*)
    via Kubernetes-style **RoleBindings** — *(principal) holds (role) at (scope)*, scope
    = global or a specific lab. Adds **groups** (users ∈ 0..N), **owner-delegated
    grants** (a lab owner / `lab:grant` holder binds lab-scoped roles to users or
    groups on their lab, under an anti-escalation rule), splits `lab:create` into
    `lab:create` (global, new lab) + `lab:edit` (per-lab), and adds a baseline `user`
    global role with no permissions (the default for new users).

    **Implemented (2026-07-23).** Full model + as-built notes in `docs/rbac-v2.md`.
    Shipped: the scoped permission catalog + resolver, `require_global`/`require_lab`
    guards, per-lab filtering of `GET /labs` and the `/events` stream, per-lab
    permissions on the lab detail/summary payloads, the grants + groups + roles +
    `/principals` APIs, per-lab terminal scoping, and the frontend (per-lab action
    gating, lab Access panel, Groups admin, live role catalog). One migration (`0008`)
    creates `groups`/`group_members`/`role_bindings`, backfills `owner_id` and
    `user_roles` → global bindings, and drops `user_roles`. **Migration note:** users on
    a pre-v2 role (`operator`/`viewer`) resolve to no permissions until re-assigned to a
    v2 role.

### Async job model (contract delta 12) · **done**

12. **The four long operations are async jobs (implemented 2026-07-29).**
    Deploy/configure/destroy/suite-run return **202 + a Job**; callers poll
    `GET /labs/{name}/jobs/{id}` (list endpoint + client `wait_job` beside it).
    Jobs persist in a `jobs` table (migration 0011); a partial unique index —
    one `running` row per lab — is the operation mutex (409 `job_in_flight`,
    any kind; it subsumed the deploy CAS and gave configure/destroy/suite-run
    a mutex they never had). Failed = could-not-run with the error envelope on
    the job; `config_failed`/`validation_failed` remain job successes.
    Startup/shutdown sweeps fail orphaned jobs (`backend_restart` /
    `backend_shutdown`) and unwedge `deploying` labs (closing the Phase 1.1
    reconciler TODO). Single-process assumption (bare uvicorn, 1 worker).

    **~~Deferred: SSE job events.~~ CLOSED by contract delta 16 (2026-07-30).**
    The `/events` stream now carries two **named** events — `lab` (the container
    relay) and `job` (`{lab, job_id, kind, status, timestamp}`, emitted at
    submit and at the terminal state) — exactly the deferred design: an
    in-process broker feeds each connection's bounded queue (lossy by choice,
    drop rather than stall the job runner), and the client's SSE parser
    discriminates `event:` names, skipping ones it has no parser for. The event
    is a poke, never the result; there is NO replay on reconnect, so the
    frontend's jobs poll slowed to a 15s fallback rather than being deleted.
    Shipped alongside delta 15 (`GET /jobs`, the cross-lab job listing).

### External SSH access — jump service (contract delta 13) · **done**

13. **Standard SSH access to lab nodes from outside, scoped by RBAC
    (implemented 2026-07-29).** A compose-owned OpenSSH jump service (`jump/`,
    published on `JUMP_PORT`, default 2222) replaces the old hand-configured
    host `lab_jump` user. Users register SSH **public keys**
    (`/auth/ssh-keys`, migration 0012; fingerprints globally unique — a key
    identifies one person); sshd's `AuthorizedKeysCommand` resolves each new
    connection live against the backend (`/internal/ssh/authorized-keys`,
    shared-token guarded, registered outside `/api/v1` so the frontend proxy
    can't expose it): one authorized_keys line restricted to
    `permitopen="<node-ip>:*"` for every node of labs where the key's owner
    holds `lab:terminal` (owner-implicit included). Besides bring-your-own
    -key, `POST /auth/ssh-keys/generate` issues an ed25519 pair server-side
    (ssh-keygen subprocess, private key returned once, never stored).
    Fail-safe invariant: an
    empty permitted set renders NO line (a permitopen-less line would mean
    unrestricted forwarding). The jump sits on the plain compose network —
    containerlab's iptables rules make lab mgmt bridges reachable without
    host networking. `GET /ssh-access` advertises the coordinates
    (`SSH_JUMP_ADDRESS`); usage is plain
    `ssh -J jump@host:2222 <user>@<mgmt-ip>` — Ansible/netmiko/scp-ready.
    Revocation (key delete, grant removal, user deactivation) bites on the
    next connection; established tunnels survive until closed.

### Playwright e2e UX suite · **done** (2026-08-06)

14. **A comprehensive end-to-end test suite driving the real frontend with
    Playwright (Apache-2.0), verifying the UX** — decided 2026-07-31, **SHIPPED
    2026-08-06** as the top-level **`e2e/`** project (pnpm + @playwright/test,
    chromium). Structure as designed at pickup: it owns a dedicated parallel
    compose project, **`twinlab-e2e`** (the nokia port-shift pattern — 5373/
    2422/8290/8291, pool 10.79/16, own `LAB_FILES_DIR`), and every run starts
    from a REAL EMPTY backend: `e2e/scripts/stack.sh reset` sweeps leftover
    e2e lab containers/networks/bridges/park-netns, drops the volumes, clears
    lab files and brings the stack back up (fresh migrations + RBAC seed +
    bootstrap admin). Three Playwright projects — `setup` (the login spec,
    which saves the admin storageState), `fast` (31 specs, no containers:
    empty states, users/groups, lab creation, the visual builder incl.
    drag-to-connect, text mode + rejection surfaces, template library, import
    wizard, account credentials, role gating with a second signed-in context,
    command palette) and `journey` (19 specs deploying the purpose-built
    `e2e-net` — an OSPF triangle of two VyOS + one FRR with two linux hosts on
    a LAN and a stub, pullable images only — through deploy + config push +
    config-time gate, nodes/logs/terminal, link table + netem both ways +
    canvas edge panel, on-demand validation + facts, drift + Changes diff +
    redeploy, whole-lab power, destroy/delete). One worker, ordered stateful
    specs, exact-string assertions throughout; **51/51 green from reset in
    ~5 min**. It caught four real bugs, all fixed: published templates served
    the source lab's pinned mgmt subnet (every instantiation 409'd), clab-api's
    netem mutex broke concurrent lifecycle/netem calls (backend now serializes
    its own netem ops and retries the busy rejection), clab-api 500s
    transiently under read bursts (bounded retry on the idempotent verbs), and
    the compose `/var/run/netns` bind's default-private propagation broke
    containerlab's interface parking — node/lab STOP of linked nodes failed
    outright (now `rshared`). Two timing truths the specs encode: the lifecycle
    badge flips to `deployed` when containers are up while the JOB runs on
    (the Last-operation badge is the real barrier), and job rows are buttons
    named `<kind> <status>, open details`.

### Test-suites v2 — render → execute → parse → assert (contract delta 17) · **done**

15. **The test-suites rework, designed greenfield after a tooling survey and
    SHIPPED 2026-08-03.** Contract delta 17 in `docs/twinlab_client_shape.py`,
    reviewed item-by-item and approved 2026-08-03; implemented the same day
    across backend (facts + pipeline + migration 0015), runner (netmiko
    interactive exec), client (v2 shapes + `facts()`), blackbox (110/110
    green incl. a live fact-templated deploy test) and the frontend panel
    (CodeEditor authoring, Facts viewer, rendered command + compare diff).
    **Live verification on the IOL MPLS lab:** the unified device-keyed
    example suite passed 25/25 (TextFSM OSPF + the Twinlab LDP template +
    rendered VRF-loopback FIB checks) and the interactive runtime suite
    proved both cross-VPN pings at 100% through the netmiko channel —
    side-by-side with the one-shot exec path truncating after the first
    packet. Also fixed en route: Ansible's libssh plugin resurrects
    known_hosts via rename-over-symlink, breaking every post-redeploy config
    push with "host key mismatch" — the runner now re-points the symlink
    before each configure.

    **Survey result — no framework adoptable as the engine** (verified against
    repos/licenses 2026-08-03): netlab `validate` (plugins only for
    eos/frr/cumulus/linux/crpd — nothing for vyos/iol; `valid:` is raw Python
    eval of user strings; text-only output, CLI-only harness), NAPALM full
    stack (napalm-vyos last tested on VyOS 1.1.7), nuts (stale 2024,
    pytest-shaped), SuzieQ (poller app, no VyOS; license fine — plain
    Apache-2.0), Batfish (offline snapshots, no live state), Robot Framework
    (keyword DSL = user code), pyATS/genieparser (parsers require the
    binary-only `genie.metaparser` wheel — fails the open-source bar in
    spirit), ANTA (Arista-only, but its declarative catalog → typed inputs →
    async runner → structured results architecture is the design reference).
    Cross-cutting: nothing supports docker exec (our only channel to
    sshd-less linux nodes), and VyOS is the coverage gap in every ecosystem.

    **Live-verified foundations (2026-08-03):** VyOS needs no parsing layer —
    FRR's `vtysh -c "show ... json"` over plain docker exec returned full
    structured JSON for OSPF neighbor (`converged: Full`), LDP neighbor
    (`state: OPERATIONAL`) and BGP VPNv4 (`show bgp ipv4 vpn summary json`,
    NOT `vpnv4 unicast` — that spelling is unknown to FRR). IOL show output
    parses cleanly through ntc-templates 9.2.0 (`parse_output("cisco_ios",
    "show ip ospf neighbor", stdout)` → typed records; 143 cisco_ios
    templates incl. BGP-VPNv4/cef/mpls-interfaces/vrf; NO template for
    `show mpls ldp neighbor` — we ship our own; vyos has only 3 Vyatta-era
    templates, irrelevant given vtysh JSON).

    **Composition chosen instead** (user-decided 2026-08-03): keep the
    runner's `netlab exec` transport, job model, RBAC and stage semantics;
    each test becomes a pipeline — Jinja2-render command/expectations
    against pinned per-node facts from the expanded topology (kills
    hardcoded IPs; sandboxed + StrictUndefined), execute per NOS,
    optionally parse (`json` | `textfsm` via ntc-templates + Twinlab
    overlay templates), assert with napalm-validate's `compare` grammar
    over parsed data (raw contains/not_contains/matches stay for unparsed
    output — regex fallback is a user decision, always available).
    Device-keyed `TestCase`s let one suite serve several NOS flavours —
    VyOS + IOL being the pair that motivated it; since IOL's withdrawal the
    worked example is `examples/mixed-nos.test-suites.json` with FOUR — and a
    node whose device has no case reports `skip`, the reserved status finally
    used. `interactive: true` routes
    a case through netmiko's persistent channel where transport is SSH
    (in scope NOW — fixes IOS truncating `ping ... repeat` on one-shot
    exec; no-op over docker exec — **superseded by delta 28**, see below). Comparator: IMPORT napalm and use
    `napalm.base.validate.compare` (own reimplementation only if the dep
    proves painful — user's call 2026-08-03). Parse failure/missing
    template = `error` result, never a silent raw fallback (netmiko's
    use_textfsm footgun, excluded by design).

    **Architecture (not in the contract):** rendering + parsing + compare in
    the BACKEND (it already runs `netlab create`; node facts persist as a
    regenerable JSONB beside the link table); netmiko in the RUNNER (the
    inventory owns SSH creds — no Twinlab-owned cred handling). New deps
    when approved for implementation: backend `napalm`, `ntc-templates`,
    explicit `jinja2`; runner `netmiko`.

    **Review resolutions (all user-decided 2026-08-03):** (a) the fact
    namespace starts as netlab's RAW node dict — provisional, deliberately
    unpinned; **pinning a stable subset is a pre-v1.0 decision** (DONE
    2026-08-05 — contract delta 26, the promised core + `_extras`
    partition; see the Road to v1.0 list and `docs/fact-namespace.md`) —
    and a `GET /labs/{name}/facts` endpoint ships now (authoring
    discoverability AND the insulation layer that pinning then used); (b) `compare` ⟺
    `parse` stays strict; (c) NO v1→v2 data migration (dev-phase, no
    real-world stored suites; repo example suites rewritten to v2); (d)
    CASE-level device keying confirmed over field-level (one atomic recipe
    per device, no key-consistency rules; a `default`-case merge is a
    possible additive extension if duplication ever bites); (e)
    `interactive` is a deliberate no-op over docker exec — **REVERSED
    2026-08-10 by contract delta 28**: a silent no-op is not something a
    caller can see, so over docker it now opens a PTY-backed
    `docker exec -it` session. Implementation
    train: backend → client → blackbox → the frozen frontend panel
    rebuild.

### Parked backend batch — order agreed 2026-08-03 · **done 2026-08-04** (16.1–16.4 shipped; 16.5 scenarios SHELVED post-v1.0, its v1.0 remnant delta 24 shipped)

16. **The remaining parked backend items** (detailed in
    `docs/frontend-rework.md`'s parked list) run in this order, small quick
    wins first, the two design-heavy items last:
    1. **Device/image catalog endpoint** — **DONE 2026-08-03 (contract delta
       18)**: `GET /catalog`, curated set + drift-guarded module/image
       mirrors + best-effort presence via the runner's `GET /images`; the
       builder now consumes it (outcome in `docs/frontend-rework.md`).
    2. **Deployed-definition snapshot + server-side topology layout** —
       **DONE 2026-08-03 (contract delta 19)**: a successful deploy snapshots
       the definition it deployed (`deployed_definition` on the detail,
       derived `definition_drifted` on list + detail — a hint, never a gate;
       cleared on destroy; PUT's YAML normalization filters cosmetic edits,
       so only changes surviving it flag), and `GET/PUT /labs/{name}/layout`
       stores ONE shared manual arrangement per lab (opaque canvas-id keys,
       full-replace PUT on `lab:edit`). Frontend: `drifted` header badge, a
       Changes diff view on the Definition card, the Build tab as the only
       layout writer, and the Overview canvas read/operate-only
       (maintainer's call 2026-08-03); localStorage layouts retired.
       **Extended 2026-08-04 (contract delta 20):** the layout resource also
       carries per-group canvas styling (`groups: {name: {color}}`, hex-pinned
       `#rrggbb`, migration 0018 wrapped the stored shape to
       `{positions, groups}`) — presentation belongs on the layout, never in
       the definition netlab validates. Builder nodes wear membership dots;
       the inspector's group blocks pick the color; unstyled groups get a
       deterministic name-hashed default client-side, so the server stores
       explicit choices only.
    3. **Builder link attribute forms** — **DONE 2026-08-04** (frontend-only,
       no contract change; slotted same day). The extras-passthrough pattern
       extended to links: dict-form and interfaces-form links parse (endpoints
       discriminate via the declared-node set; netlab expands both forms
       identically — verified live), links carry a typed name plus lossless
       link-level and per-endpoint extras, and one-endpoint stubs became a
       third link kind with canvas terminator nodes. `examples/campus-lan.yml`
       is fully buildable visually; its original vs builder-emitted netlab
       expansion is byte-equal. Still text-editor territory: link groups,
       the dict-of-lists `links:` shape, self-links. Outcome detail in
       `docs/frontend-rework.md`.
    4. **Definition input methods** — full-network templates, single-node
       templates, definitions built from real config files. Started with the
       design discussion (2026-08-04) and split there: **part one — the
       template library — DONE same day (contract delta 21)**, approved with
       one review revision (per-KIND collections `/templates/network` +
       `/templates/node` instead of a flat catalog — no consumer wants the
       union, a shared namespace only manufactured collisions). Decisions:
       clone-and-edit (parameterized templates recorded as a future
       consideration; netlab's native `components` — live-probed: expands
       `include` nodes to `<instance>_<inner>` names via generated
       `inc_<instance>` broadcast groups — reconsidered later as builder
       coverage); user-tier network templates are PUBLISHED LABS (live view,
       `PUT /labs/{name}/template`, new global-only `template:manage`,
       publishing deliberately exposes the definition deployment-wide); node
       templates are snapshot fragments (structural validation only); builtin
       tier seeded from `examples/` with a drift-guard; NO instantiate verb.
       Shipped across backend (migration 0019) + client + blackbox (9 tests)
       + frontend (create-from-template, palette stamping,
       save-node-as-template, header publish toggle). **Part two —
       definitions from real config files — DONE 2026-08-04 (contract delta
       22)**, unparked ahead of scenarios (maintainer's call), designed and
       shipped the same day; full record in **`docs/config-import.md`**.
       Decided at design: one deployment model (a raw-clab second model was
       considered and REJECTED — interface renaming and link inference are
       needed either way, and a second lab species forks the whole stack);
       import is a pure definition factory (thin skeleton —
       nodes/links/pinned addressing, NO modules — plus verbatim carry as
       custom-config and a pinned mgmt/auth/telemetry/hardware quarantine,
       nothing ever dropped: the three buckets partition the source, a
       tested invariant); interface renaming via the dry-create expanded
       topology joined on pinned addresses; a stateless post-configure
       fidelity diff (`POST /labs/{name}/config-diff`). Parsers: netutils
       (Apache-2.0, approved) for IOS, own boundary parser for VyOS (nothing
       off-the-shelf exists; Batfish set aside — no VyOS, heavyweight;
       ciscoconfparse2 GPLv3-blocked). Shipped across backend
       (`services/configimport/`, `/import/*` + config-diff +
       `CatalogDevice.config_import`) + client + blackbox (7 tests, 130
       total green live incl. the flagship deploy round trip: import two
       VyOS configs → compose → deploy with configure → zero missing lines
       in the diff) + frontend (the `/labs/import` wizard and the builder's
       "From config file…"). Live-proven en route: compose order is
       put_custom_config BEFORE update_definition; VyOS op-mode collection
       needs the vyatta-op-cmd-wrapper over docker exec. **The aux-input
       analysis followed IMMEDIATELY (as sequenced) and became contract
       delta 23 — explicit wiring — APPROVED and SHIPPED 2026-08-04.**
       Maintainer's decisions: wiring list only (CDP/LLDP neighbor dumps
       PARKED, groundwork noted — ntc-templates already parses the IOS
       output and they would normalize into the same entries); the wiring
       is REQUIRED and inferred adjacency is REMOVED (topology is intent —
       import stops guessing it, and the same sources + wiring always give
       the same lab); the subnet join demoted to a suggestion generator
       (`POST /import/wiring-suggestion`) that only prefills the wizard's
       editor. Per-interface realization stays (loopback pins, mgmt
       quarantine, stubs for unwired addressed interfaces — the twin's
       boundary); contradictions became 422s (`wiring_invalid` /
       `wiring_conflict`, carrying the entry index); all-unnumbered wires
       emit `prefix: false` L2 links — the unnumbered-core/trunk/LAG-member
       case addressing could never see — and mixed wires spell `ipv4:
       false` on their unaddressed endpoints, since netlab otherwise
       invents an address (live-proven). Blackbox 133 green, the flagship
       round trip now carrying an L2 wire end to end. Next was scenarios —
       which were then SHELVED at the opening of their design discussion; see
       16.5 for what shipped in their place.
    5. **Scenario definition** — **SHELVED until after v1.0** (maintainer's
       call 2026-08-04, at the opening of its design discussion). What shipped
       for v1.0 instead is the minimal primitive the discussion surfaced:
       **batch runtime actions — DONE 2026-08-04 (contract delta 24)** — one
       request setting/clearing MANY netem impairments and node power events,
       so a caller (frontend or external orchestrator) can stage a whole
       degraded condition without round-trip choreography. Approved with one
       review revision: TYPE-unified with the single verbs, not route-merged
       (a batch netem item IS the single route's body + node + kind; the
       single routes keep their fail-loudly HTTP errors, since a batch item's
       failure is data — merging would kill one or leave `ok` a dead field);
       `set_netem` took `NetemAction` so an impairment has ONE spelling
       client-wide. Sequential in request order, continuing past failures,
       index-aligned report, 422 up front with nothing executed, ≤64 items,
       sync (so runtime control survives the per-lab job mutex),
       `lab:configure`. Shipped across backend (one shared executor —
       a standalone verb is a batch of one) + client + blackbox (136 green
       live) + the frontend, where the two-endpoint link fan-out became one
       call with honest partial-failure reporting. **This closes the parked
       batch.** The scenario analysis groundwork is
       recorded so the post-v1.0 pickup doesn't re-derive it: a scenario is
       a declarative, repeatable TIMELINE of runtime actions against a
       deployed lab (the runtime counterpart of a test suite — re-run after
       a config change and compare), and it composes almost entirely from
       existing verbs (netem, power control, suite runs as assertion steps,
       the job model, `last_validation`-style persistence). The only
       genuinely NEW machinery is traffic generation and the time axis.
       Grounded facts (probed 2026-08-04): the VyOS image ships
       iperf3/iperf/mtr/nping; netlab's clab default image for `linux` is
       `python:3.13-alpine` (busybox ping/nc/wget only — iperf3 flows need
       an image decision); IOL has only IOS ping (the netmiko interactive
       channel already solves its exec truncation). Recommended-but-undecided
       at shelving: sequential-runbook time model (no user code, house
       rule); flow types ping (universal) + iperf3 (`--json` output feeds
       the napalm compare grammar); scenario references EXISTING nodes only
       (never injects probes — the rejected-FRR-probe reasoning);
       snapshot-restore cleanup (17.2's `tc:` decision of 2026-08-05
       settled the shared question: there is NO baseline tier, so a
       scenario snapshots the live impairment via the link table and
       restores by re-submitting a delta-24 batch); a scenario run
       is a job, which forces the first job CANCEL verb and a progress
       surface; permission `lab:configure`, no new grant.
    Each contract-touching item goes through the review gate
    (sketch → user review → implement). Also due before the tag, independent
    of this batch: **pin the fact-namespace subset** — **DONE 2026-08-05**
    (contract delta 26: the promised core + per-object `_extras`, closing the
    delta 17 resolution; `docs/fact-namespace.md`).

### NOS platform sweep — and the two reviews it informs · **CLOSED 2026-08-05** (17.1 closed for v1.0, 17.2 closed by rejecting gap 1 / delta 25, 17.3 shipped Tier A 2026-08-04 + Tier B 2026-08-05; opened 2026-08-04, added 2026-08-03, scoped 2026-08-04)

17. **One work item with three strands, run in parallel.** The sweep is the
    driver; the two reviews were previously carried as unsequenced items 18 and
    19 and were folded in here (maintainer's call 2026-08-04) because both are
    *informed by what the sweep finds* — the platform matrix decides what an
    image pre-flight must cover and where the builder's typed core actually
    falls short. They run alongside the sweep, not after it.
    **Numbering note: 18 and 19 are RETIRED, not missing.** They were exactly
    those two reviews, and they live on as 17.2 and 17.3; nothing was dropped.
    Do not reuse either number — the next new item takes **24** (22 is the release
    train).

    **Opened 2026-08-04 with three parallel analyses, recorded in
    `docs/nos-sweep/`** (acquisition matrix, full up-parity audit, builder
    coverage inventory — the README there carries the decision log). The
    strand texts below predate those analyses; where they disagree, the docs
    are authoritative. Corrections so far: netlab's `tc:` has SEVEN knobs to
    our netem API's five (`duplicate`/`reorder` are not expressible over
    clab-api netem), the up-parity gap list is seven items, not three (the
    inline-deploy bind loss is device-wide — it breaks `/etc/hosts` on the
    supported `linux` device and blocks FRR/XRd/cRPD/cSRX/cumulus/daemons
    config entirely — plus up/down shell hooks, OVS bridge type, and topology
    `message`), and `netlab down` adds no gap beyond tools + hooks.

    **17.1 — Research, obtain, and test as many NOSes as possible.**
    containerlab's kinds list is the starting inventory, netlab's device list
    the cross-check. We cannot *distribute* proprietary images (the open-source
    constraint applies to what we ship, not what we test against), but we can
    obtain them legitimately, confirm or deny Twinlab support per platform, and
    use them ourselves. The expected side effect is the real payoff: every new
    NOS stresses deploy, config push, interface naming, facts, parsing and
    validation differently, so the sweep is also a bug hunt across the whole
    stack before v1.0. Widening CLAUDE.md's supported set — **VyOS + IOL when
    this paragraph was written; VyOS, FRR, MikroTik CHR, bird, dnsmasq and linux
    today, IOL having been withdrawn on licensing (below)** — is
    explicitly "a maintainer decision that starts with testing" — this strand IS
    that testing. Prior art: Nokia SR Linux is already proven end-to-end in the
    parallel `nokia/` work; SR OS (TiMOS) is blocked on a client-provided
    qcow2 + license (see `docs/nokia-sros.md`). Scope, the platform matrix, and
    what "supported" formally requires (deploy? config push? facts? suites?)
    are designed when picked up.

    **The CML licensing decision, and Cisco IOL's WITHDRAWAL (2026-08-05).**
    Cisco's reference-platform VM images — the only legitimate source of IOL —
    are licensed for use inside Cisco Modeling Labs only. Cisco's own docs are
    unambiguous: *"The Cisco VM images that are provided for download with
    Cisco Modeling Labs or as part of the CML refplat ISO file are only
    licensed for use within Cisco Modeling Labs"*, and *"Downloading these VM
    images and using them outside Cisco Modeling Labs without a proper license
    is prohibited"*
    ([DevNet](https://developer.cisco.com/docs/modeling-labs/vm-images-for-cml-labs/)).
    Three stances were put to the maintainer: (1) state the status quo — test
    -only use of legitimately obtained refplat images is acceptable, since
    Twinlab distributes nothing; (2) conservative — CML images stay in CML,
    which means IOL leaves the supported set; (3) grandfather IOL but do not
    expand. **Maintainer's call: stance 2, "for now".**
    So IOL is WITHDRAWN — on licensing, never on behaviour: it deployed,
    configured, held OSPF/LDP/VPNv4 and passed 25/25 of its suite. Withdrawal
    ran the admission procedure in reverse (catalog + frontend fallback, the
    `cisco.ios` runner collection, the example and its builtin network
    template, the suite's iol cases, every doc claim); `DEVICE_KMODS` and
    hostprep needed nothing, since iol carries no netlab kmods key. What
    deliberately STAYED, because the mechanisms are generic and device-
    agnostic: the config-import IOS parser (`POST /import/*` still accepts
    `device: iol`; only the catalog's `config_import` flag can no longer
    advertise it), the `textfsm`/`cisco_ios` platform map with Twinlab's own
    LDP template, and the `mpls_te`/`ip_sla` built-in custom-config templates —
    they ARE the built-in library, and emptying it would delete a shipped
    capability rather than withdraw a platform.
    Consequences worth knowing: an iol definition still PUTs and may still
    deploy (nothing rejects an uncatalogued device), but it edits as TEXT only
    (the builder's unknown-device gate) and its missing image degrades from a
    fast `image_missing` job failure to a warning plus a late clab-api error.
    It also cost coverage, and the two halves have since diverged: the example
    suite's loss of its second live flavour — leaving device-keyed cases, the
    `textfsm` parse mode and `compare`-over-parsed-output with no worked
    example — was **CLOSED 2026-08-05** by `examples/mixed-nos.test-suites.json`,
    which restores all three across FOUR flavours. **Still open** is the
    dnsmasq `dhcp` module path: IOL was its only candidate client, and under the
    clab provider `linux` has no `dhcp` support (netlab lists it libvirt-only),
    so nothing in the admitted six can exercise it — it needs a future platform,
    and is the one live sweep follow-up from this withdrawal.
    Everything below the CML line is now out of reach too:
    CML-Free's extra IOL versions and ASAv, and CML Personal's IOSv/IOSv-L2/
    CSR1000v/cat8000v/n9kv. **Cisco is not entirely closed** — XRd Control
    Plane and the Cisco 8000 emulator ship under separate entitlements, not
    the CML SEULA, so they remain acquirable if a Cisco service contract turns
    up (XRd also needs no KVM and is light).
    **Revisit stance 1 after v1.0** — see the dedicated item below.

    **Nokia SR-SIM: PARKED 2026-08-05.** Nokia's containerized SR OS
    (netlab device `srsim`, clab kind `nokia_srsim`, no KVM) is the better
    long-term Nokia target than the vSIM VM and would delete the top SR OS
    risk — vrnetlab wires its datapath with tc `mirred` filters on the very
    interfaces Twinlab writes netem to, and SR-SIM has no vrnetlab wrapper at
    all. It was NOT added to the client ask, for two reasons recorded here so
    the pickup doesn't re-derive them: it is 25.x-era only, so it cannot run
    the releases the client actually holds (TiMOS 22.10.R3 / 24.10.R7), and
    its licence is an ANNUAL SUBSCRIPTION mounted at
    `/nokia/license/license.txt` — the container refuses to boot without one
    and reboots when it expires, so it trades vSIM's KVM/RAM cost for a
    recurring renewal obligation. When picked up: probe the INTEGRATED
    (pizza-box) chassis first — the distributed ones are one CPM container
    plus an IOM container per line card sharing a netns
    (`network-mode: container:<cpm>`), i.e. several containers per netlab
    node, the same class of problem that got `kind` denied. Note also that the
    Nokia work all lives on the parallel `nokia/` tree and has never reached
    `dev`: this runner has no `nokia.grpc`/`nokia.srlinux`, no
    `grpcio`/`protobuf`, and no
    `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` (needed because
    nokia.grpc 1.0.2's generated protobuf code is rejected by the C++/upb
    runtime, and netlab's own fix pins a protobuf with no Python 3.13
    wheels). **SR Linux is the cheap win parked with it** — free, public
    (`ghcr.io/nokia/srlinux`, no account, no licence) and already proven end
    to end on the `nokia/` branch; admitting it on `dev` needs only those
    four runner items plus a `netlab-defaults.yml` connection entry, with no
    acquisition and no licensing question. Detail in
    `nokia/docs/nokia-sros.md`.

    **The acquisition ask is PARKED to after v1.0 (2026-08-05, maintainer's
    call) — see item 21.** Everything left in 17.1 that needed the maintainer to
    register for an account, accept terms or buy something (cEOS, the vJunos
    trio, FortiGate, Aruba, cRPD/cSRX, XRd) stops blocking v1.0. That is a
    scope decision, not an abandonment: the sweep already did its job as a bug
    hunt (seven up-parity gaps found, six shipped; the runner-collection trap;
    CHR's missing netmiko driver; two wrong catalog module mirrors), and the
    supported set it settled — VyOS, FRR, CHR, bird, dnsmasq, linux — is a
    coherent, tested six. **What remained in 17.1 for v1.0 was exactly one thing:
    the large mixed-NOS topology** over that set, which needed nothing from
    anyone — and it **LANDED 2026-08-05, so 17.1 IS CLOSED for v1.0** (below).
    The last open item, gap 1 (delta 25, in 17.2), was decided and shipped
    2026-08-05 — as a rejection — so **item 17 is CLOSED**. 17.3's Tier B
    review shipped the same day.

    **The mixed-NOS lab — DONE 2026-08-05, closing strand 17.1 for v1.0.** Every
    platform above was admitted on its own two-node probe;
    `examples/mixed-nos.yml` puts all six in ONE network, because a platform that
    configures fine alone can still get its interface names, addressing or
    adjacencies wrong beside another vendor. The four routing platforms sit in a
    **full mesh**, so all six cross-vendor OSPF pairings are proven by one deploy
    instead of six labs, next to a three-endpoint services LAN (so the hostprep
    bridge path is in play), a host behind CHR, and a stub — seven nodes, nine
    links, and all three config-push paths at once (Ansible `docker`,
    `network_cli` over SSH, host-side netns scripts). **Green on the first
    attempt:** `status="configured"`, all six adjacencies Full, forwarding end to
    end across two platforms, the link/interfaces/facts/netem/batch surfaces
    correct across four NOS families, and the config-time gate passing 8/8 on a
    mixed lab. `examples/mixed-nos.test-suites.json` also **restores the worked
    examples the IOL withdrawal cost us** — device-keyed dispatch across FOUR
    flavours, `parse: json` + compare, and `parse: textfsm` + compare — 9/9 live
    with nothing hardcoded, and it gave `interactive: true` on CHR its first live
    verification. Full evidence in `docs/nos-sweep/results.md`.
    **One caveat on that verification, because it is the parked FRR item biting:**
    the verified run gave frr1 a locally-built image carrying gnupg+curl. FRR's
    config push is the one non-hermetic push in the admitted set and it cannot
    succeed on this host with netlab's default image (below). The committed
    example deliberately keeps netlab's default — it is the portable choice and
    works wherever lab nodes have DNS — and documents the two-line workaround in
    its header. Every other node ran exactly the image the example names. So
    `examples/mixed-nos.yml` deploys as-written on a normal host, and needs that
    one override HERE until the FRR image question is settled.
    It paid for itself as a bug hunt, which was the point:
    **two more CHR admission gaps** (`TEXTFSM_PLATFORMS` had no routeros7 — on
    the one admitted platform with no JSON output — and ntc-templates cannot
    parse RouterOS 7 at all, both its templates being v6-shaped, so Twinlab now
    packages its own); **one real Twinlab bug** (a resolved-but-mismatched
    TextFSM template raised through the boundary and failed the whole suite run
    instead of erroring one check — pre-existing, reachable on any device whose
    ntc template targets a different NOS release); a stale device list in the
    frontend's build-doc harness (bird and dnsmasq were never added); and two
    netlab semantics documented rather than worked around (a daemon-role node's
    links type `lan` while OSPF still runs point-to-point on them, and it gets a
    router ID but no loopback INTERFACE, so that ID is deliberately not
    pingable). Since CHR has now tripped three of the five admission steps — the
    Ansible collection during its own probe, then the netmiko driver and the
    TextFSM path only after it was admitted — the
    procedure doc gained a rule: after admitting a platform, exercise an
    `interactive: true` case and a `parse:` case against it — the probe protocol
    walks neither path, and both failures are clean typed errors that hide.
    **One finding was raised as a contract question rather than fixed, then
    DECIDED AND SHIPPED the same day:** a stub link reported
    `oper_state="down"` while forwarding perfectly, because a dummy interface's
    live state is the literal string `"unknown"` and the pinned delta-14 roll-up
    treated known-not-"up" as down. It affected every stub on every supported
    platform (two different realizations, both landing on a dummy interface) and
    `campus-lan.yml` too, and nobody had ever decided it — the roll-up's table
    test has rows for `None`, `"down"` and `"lowerlayerdown"` but none for that
    string. **Maintainer's call: read the interface `kind` as proposed, AND make
    `unknown` the reporting default instead of `down`.** So endpoint
    classification is now two stages — down is a CLOSED set
    (down/lowerlayerdown/notpresent), anything unrecognized reads unknown rather
    than being assumed down, and a carrier-less `dummy` reporting "unknown" reads
    up. Delta 14's WORDING is amended with no shape change and no new wire field
    (clab-api already reports the kind, and `merge_links` already holds the
    matched interface), plus a consumer obligation on `LinkEndpoint.state`: never
    read `state != "up"` as down.

    **Parked out of 17.1, to reconsider later (2026-08-05)** — the diagnoses
    live here; **item 21 is the pickup list** that carries them past the tag, so
    read this for the "why" and item 21 for the "when":
    - **FRR's config push is not hermetic.** netlab's FRR initial script
      installs gnupg+curl (`linux/packages.j2` installs whatever is missing)
      and the official `quay.io/frrouting/frr` image ships neither, so every
      FRR config push needs working egress AND DNS *from inside the lab node*.
      On this host it fails outright: containerlab fills each node's DNS from
      the host's `/etc/resolv.conf` and drops the two IPv4 resolvers because
      they sit in the CGNAT range (100.64.0.0/10), leaving IPv6-only
      nameservers an IPv4-only node cannot reach. FRR is the ONLY admitted
      platform with this property. The fix is proven and is NOT a DNS change:
      an image carrying gnupg+curl (`FROM quay.io/frrouting/frr:10.6.1` +
      `apk add --no-cache gnupg curl`) deploys, configures and reaches OSPF
      Full on this host **with DNS still broken**, because the script only
      installs what it finds missing. The cost is that the catalog's `image`
      would stop being netlab's default, which
      `test_image_mirror_matches_installed_netlab` asserts — so it needs a
      deliberate "ours on purpose" guard rather than a quiet edit. Full
      evidence in `docs/nos-sweep/results.md`.
    - **ansible-core 2.21 removed the `paramiko` connection plugin**, which
      netlab still names for openbsd, srlinux and sros under the clab provider
      (verified by reading every device profile — everything else already uses
      docker or network_cli). It is gone from core with no redirect and is not
      in ansible.posix, community.general or ansible.netcommon. **RESOLVED
      2026-08-05** by `netlab-runner/netlab-defaults.yml` →
      `/etc/netlab/defaults.yml`, which netlab merges over its packaged device
      data so the override lands at create time; only openbsd has an entry, as
      the right replacement is per-device (`ssh` for a plain host,
      `ansible.netcommon.libssh` for a network OS). srlinux and sros get theirs
      when their probes run — both matter to the `nokia/` branch.
    - **OpenBSD, PARKED 2026-08-05.** Pinning `vrnetlab/openbsd_openbsd:7.7`
      (the version netlab targets) fixed 7.9's two failures, which shared one
      cause — vrnetlab's launcher never waits for its `cloud-localds` before
      starting qemu. Both nodes now boot, pass readiness and authenticate, and
      with the connection override above the config push runs. ONE blocker
      left: `netlab initial` reaches "Execute /tmp/config.sh to deploy initial
      config" and hangs there past 500s, most likely a TTY/pty expectation over
      the plain `ssh` connection. Evidence in `docs/nos-sweep/results.md`.

    **17.2 — The honest remainder of the `netlab up` parity audit
    (2026-07-31).** The audit found `netlab up`'s clab pre/post hooks have
    exactly two members — host bridges and kernel modules — both since owned by
    the hostprep sidecar. Three gaps remain, each a silent-ignore of valid
    definition content or a late opaque error; "never silent" is the agreed
    principle, and **each needs a maintainer decision before implementation**:
    - **`tc:` link/interface attributes are silently dropped.** First-class netlab
      schema (SEVEN knobs — delay, jitter, loss, corrupt, duplicate, reorder,
      rate — vs the netem API's five: `duplicate`/`reorder` don't exist on the
      clab-api netem path), applied by `netlab up` after
      start via `execute_tc_commands`. A definition carrying `tc:` validates and
      deploys with no impairment — violating definition-is-source-of-truth.
      Decided 2026-08-04 to honor it (delta 25 sketched: deploy applies through
      the delta-24 executor, power verbs reapply, clear reverts to baseline),
      then DEFERRED to the end of item 17 for re-analysis.
      **REDECIDED 2026-08-05 — REJECT at PUT for v1.0, reconsider later;
      SHIPPED same day** (422 `unsupported_directive`, one entry per placement,
      the key naming the link entry — `defaults.tc.enable` and a knob-less
      `tc:`, since a node may be NAMED tc, are not rejected). The re-analysis
      probed the mapping and found it easy (`delay`/`jitter` normalize to ms;
      `tc.rate` is bit/s to our kbit/s) — the cost was elsewhere: a baseline
      needs reapply-on-restart and a "clear" that reverts, and that second rule
      changes delta 7's shipped REPLACE semantics on a v1.0 surface, for a key
      with no demand behind it. *Settles 16.5's shared question* the other way:
      **no baseline tier — the live qdisc is the only impairment state**, and a
      scenario restores by re-submitting a delta-24 batch, which needs nothing
      new. Detail and probe evidence: `docs/nos-sweep/netlab-up-gaps.md` gap 1.
    - **`tools:` is silently dropped** (graphite, suzieq, nuts, nso, edgeshark —
      side containers `up`/`down` would start). DECIDED 2026-08-04: reject at
      PUT; reconsider later. **SHIPPED same day** (422 `unsupported_directive`).
    - **No pre-flight image check** — deploy fails late with an opaque 502 from
      clab-api when an image is missing, where `netlab up`'s `validate_images`
      gives friendly pull/build hints first. *Landscape changed since the audit:*
      contract delta 18 gave the runner `GET /images` and the backend the matching
      policy (the catalog's best-effort presence), so the visibility problem is
      solved — DECIDED 2026-08-04: reject only when the deploy is impossible
      (absent + catalog-marked local-only → fail fast with a friendly
      `image_missing`; absent + pullable → proceed with a warning; runner
      unreachable → proceed). **SHIPPED same day** (`DeployResponse.warnings`,
      `CatalogDeviceSpec.local_only`). **This is why
      the strand runs with the sweep**: 17.1 multiplies the image set and is the
      first consumer of a friendly missing-image error.
    - **Four more gaps found by the fresh audit (2026-08-04, detail in
      `docs/nos-sweep/netlab-up-gaps.md`; decisions in the README there):** the
      inline-deploy bind loss (gap 4 — DECIDED and **SHIPPED 2026-08-04**:
      host-shared `LAB_FILES_DIR` + bind REWRITE, same-path invariant across
      backend and clab-api; fixes the linux `/etc/hosts` regression —
      blackbox ping-by-name, 137 green — and FRR is proven live end-to-end,
      OSPF Full, pending formal admission by the sweep), up/down shell +
      plugin CLI hooks
      never run (gap 5 — DECIDED: reject the keys and document the security
      rationale), OVS bridge type silently gets Linux bridges (gap 6 —
      DECIDED: reject at PUT, REVISIT if the sweep's L2 testing needs it), and
      topology `message` dropped (gap 7 — DECIDED: surface it). **Gaps 2, 5,
      6, 7 ALL SHIPPED 2026-08-04** (the `unsupported_directive` PUT batch +
      `LabDetail.message`); gaps 3 and 4 shipped the same day, and gap 1
      (delta 25) — the strand's last open item — was decided 2026-08-05 as a
      rejection and shipped, **closing 17.2**. All seven gaps resolved:
      four honored, three rejected loudly, none left silent.

    **17.3 — Review extending the builder's supported configuration surface.**
    The Build tab's Visual mode covers a deliberate typed core (nodes, p2p/LAN/
    stub links incl. dict + interfaces forms, groups, ospf/bgp/mpls/vrf, extras
    passthrough at every level); everything beyond it is text-mode territory.
    This strand is the deliberate review of what to promote next, in one pass
    rather than ad-hoc: the still-gated link forms (link groups and
    attribute-only entries, the dict-of-lists `links:` shape, self-links,
    interfaces mixed with node keys, hyphenated names), netlab
    `components`/`include` (live-probed at the delta-21 discussion — expansion
    semantics are understood, the builder just can't see through them yet), and
    the typed module set beyond ospf/bgp/mpls/vrf (catalog-driven; the
    device×module matrix already comes from the server; `lag` is the known
    candidate from the config-import work). The unknown-device POLICY gate lives
    in 17.1 — **that shared boundary is the second reason these run together**:
    the promotion decisions land against the supported set the sweep settles,
    and the catalog is the one surface both strands write to.
    **Scoped 2026-08-04** off the full inventory
    (`docs/nos-sweep/builder-coverage-gaps.md`): the Tier A structural-gate
    batch is AGREED — hyphenated names, nodes-as-dict-list, list-form dict
    members, dict-of-lists links (typed listName, lossless), link groups
    (expand-on-parse with notice), self-links (SUPPORT), components minimum
    step, hierarchical group members, the 16-char name cap. Tier B
    extras→typed promotions (module presence ×14, subkey splits, field
    promotions, vlans, …) are DEFERRED to their own review after the sweep
    work, before v1.0.
    **The Tier A batch SHIPPED 2026-08-04** — all nine, frontend-only. Verified
    by a 36-check round-trip harness (esbuild bundle under node), by every
    stored definition on the running stack, and against netlab 26.07 itself:
    each emitted form creates cleanly, and the builder's link-group expansion
    yields a byte-identical expanded topology to netlab's own. Saving can now
    REWRITE a document (a link group comes back expanded), so parse gained a
    notice channel distinct from the gating reasons, and endpoints are
    addressed by POSITION rather than node name so a self-link's two ends stay
    distinct. Live finding: both ends of a self-link draw the SAME pool address
    (netlab derives it from the node id), so netlab refuses one unless the link
    says `prefix: false` or each end carries an explicit `ipv4` — the link
    inspector warns where the user edits; the dry create stays the judge.

    **The Tier B batch SHIPPED 2026-08-05**, closing this strand — the review
    is §6 of `docs/nos-sweep/builder-coverage-gaps.md`, six frontend commits,
    90 harness checks. The module vocabulary became netlab's whole 18-module
    set with the checkbox offer derived from the device catalog (so one exotic
    module can no longer demote the list and take the bgp/mpls/vrf controls
    with it); the remaining whole-key demotions became per-subkey splits, the
    same per-object partition delta 26 settled for facts; and the keys config
    import emits — link `prefix`, endpoint `ifname`/`ipv4`/`ipv6`, node
    `loopback`/`config` — are typed, so an imported lab is editable without
    opening Advanced properties once. The re-analysis added node
    `box`/`role`/`group`.

    Verified by creating BOTH spellings of six documents under netlab 26.07 in
    the same directory and diffing the expanded topologies: five are
    byte-identical. The node-`group` fold is not, by exactly one key — netlab
    keeps a vestigial `group:` on the node's own dict — but the generated
    Ansible inventory is identical and no netlab code reads that key after
    expansion, so the fold is inert; its only visible cost is that the key
    leaves the fact namespace's `_extras`, the tier that promises nothing.
    **The maintainer accepted that delta 2026-08-05**, so the batch is closed
    with no follow-up.

    What remains open in this strand is only the unknown-device policy gate,
    which moves with 17.1.

### The v1.0 release train · **planned, LAST** (after item 14; nothing ships without it)

22. **Publish `twinlab-client` to PyPI and tag v1.0.** Referenced as a sequencing
    anchor throughout this file since the contract work began but never written
    down as an item — recorded here 2026-08-05 so "the release train" names
    something concrete. It is deliberately last: item 14 (Playwright) must land
    first, and the items above it in the Road-to-v1.0 list close the surfaces
    the tag freezes.

    **What is already true:** `client/` is the distributable artifact
    (`twinlab-client`, PyPI-ready, versioned 0.9.0), the `blackbox/` suite is the
    contract's enforcement against a live stack, and `docs/twinlab_client_shape.py`
    is the reviewed contract the tag pins. Nothing in the stack itself is
    distributed — Twinlab is deployed from this tree by `docker compose`.

    **What the train actually does**, to be confirmed when picked up:
    - all gates green on a clean tree — backend / client / netlab-runner / hostprep
      (`ruff format` + `ruff check` + basedpyright strict + pytest) and frontend
      (`pnpm typecheck` + `pnpm build` + `pnpm check:build-doc`);
    - the full blackbox suite, `deploy` marker included, against a freshly built
      stack — not an incrementally-patched one (the CHR re-probe is the precedent);
    - build + publish `twinlab-client` (its own version, independent of the stack's
      tag);
    - tag the repo and write release notes.

    **Pre-flight run 2026-08-06 — green, and now STALE.** Every gate, the full
    blackbox suite with the `deploy` marker against a stack reset to empty and
    rebuilt, and a clean `uv build` of the client; draft notes landed at
    `docs/release-notes-v0.9.md` (drafted as v1.0; retitled when the version was
    settled). Four commit groups have shipped since —
    contract deltas 27, 28 and 29, the digest-pinned VyOS image, and the
    shielded DB session close — so the run does not carry forward and the freshly-built
    stack requirement above applies to the re-run. The pre-flight's version
    finding is CLOSED 2026-08-11: **the tree is versioned 0.9.0 throughout** —
    maintainer decision, one version for stack and client, 0.9 rather than a
    1.0 pre-release so the door stays open for API changes before the 1.0
    promise; the client's classifier moved to `Development Status :: 4 - Beta`
    and its repository URLs now point at the public
    `github.com/IquallNetworks/twinlab` (the personal fork remote is dropped).
    (The pre-flight's other finding, a badly stale root `README.md`, was
    closed by the rewrite of 2026-08-06.)

    **Undecided, and all of it is the maintainer's call:** the PyPI account and
    whether to use trusted publishing; whether a CHANGELOG is introduced; and
    whether the tag — `v0.9.0` — is cut on `dev` or after a merge to `main`.
    **Pushing,
    merging, tagging and publishing are maintainer actions** — the standing
    convention in `CLAUDE.md` — so this item is prepared, never executed,
    unattended.

### Post-v1.0 · reconsider the CML licensing stance (stance 1) · **planned, after the v1.0 tag**

20. **Revisit whether test-only use of legitimately obtained Cisco CML
    reference-platform images is acceptable** — deferred here by the
    maintainer when stance 2 was adopted "for now" (2026-08-05; the full
    three-stance framing, Cisco's exact wording and everything the decision
    gates are in item 17.1). Nothing about this is urgent and nothing in v1.0
    depends on it; it is recorded so the choice stays a decision rather than
    becoming an accident.

    **What reversing to stance 1 would restore**, in rough order of value:
    Cisco IOL itself (re-admission is the up-to-five-part procedure plus the example,
    the builtin network template and the suite's device-keyed second flavor —
    all of it is in git history at the 2026-08-05 withdrawal commits, so it is
    a revert, not a rebuild); then CML-Free's extra IOL *versions* and ASAv,
    which is what makes a mixed-**version** topology possible without cEOS;
    then CML Personal ($199/yr) for IOSv, IOSv-L2, CSR1000v, Catalyst 8000v
    and Nexus 9300v — five platforms for one purchase, and the only realistic
    n9kv route.

    **The hedge worth examining if it is ever revisited:** Cisco's prohibition
    reads *"...outside Cisco Modeling Labs **without a proper license**"*,
    which implies an independent entitlement to the OS could cover use
    elsewhere. Whether a Cisco service contract constitutes that is a question
    for whoever holds one — not something this project can answer for itself.

    **Independent of the stance:** XRd Control Plane and the Cisco 8000
    emulator ship under separate entitlements, NOT the CML SEULA, so they can
    be pursued at any time without touching this decision. XRd is the
    attractive one — native container, ~2 GB, no KVM — and needs a Cisco
    service contract.

### Post-v1.0 · resume the platform sweep — the acquisition-blocked tail · **planned, after the v1.0 tag**

21. **The platforms that need a human before they need an engineer.** Parked out
    of strand 17.1 on 2026-08-05 (maintainer's call) so v1.0 is not gated on
    accounts, terms and purchases. The full actionable detail — every URL, what
    each account costs, the build path and what each platform unlocks — is
    `docs/nos-sweep/acquisition-checklist.md`; this is the sequencing record.

    **The ask, in the order it was already prioritized** (most coverage per unit
    of effort first):
    1. **Arista cEOS** — free account (corporate email), `docker import`, no KVM,
       ~2 GB/node, full netlab support, `network_cli` transport. **Get 2–3
       versions**: cEOS has the deepest back-catalog of anything on the list and
       is now the ONLY route to a mixed-**version** topology, since CML-Free's
       extra IOL versions went with the licensing decision (item 20).
    2. **Juniper vJunos trio** (router / switch / Evolved) — free, no licence,
       but 5–8 GB RAM and 4 vCPU *per node* with ~15-minute boots; a 3-node lab
       is this host's ceiling. Unlocks the **netconf** transport.
    3. **Fortinet FortiGate** — free FortiCare account; the only **httpapi**
       transport on the list. Evaluation licence is capacity-limited, which is
       fine for a transport probe.
    4. **Aruba AOS-CX** — support-portal account; whether a bare free account
       suffices is itself unconfirmed and is part of what the step establishes.
    5. **Juniper cRPD / cSRX** — trial downloads, low effort, and **unblocked
       since the `LAB_FILES_DIR` bind rewrite** (both deliver config through a
       `netlab-config.sh` bind that inline deploy used to strip).
    6. **Cisco XRd Control Plane** — needs a **service contract** entitlement,
       NOT the CML SEULA, so item 20's stance does not block it. Native
       container, ~2 GB, no KVM — the most attractive Cisco platform left.

    **Also parked here, not blocked on acquisition** — these need engineering
    time, not a purchase, and are written up in 17.1:
    - **Nokia SR Linux** — the cheapest win of the lot. Free and public
      (`ghcr.io/nokia/srlinux`, no account, no licence), already proven end to
      end on the parallel `nokia/` tree. Admitting it on `dev` is pure runner
      plumbing: that tree's `nokia.grpc`/`nokia.srlinux` collections,
      `grpcio`/`protobuf`, the pure-Python protobuf env var, and a
      `netlab-defaults.yml` connection entry (netlab names `paramiko` for it,
      which ansible-core 2.21 removed). No licensing question at all.
    - **FRR's non-hermetic config push** — fix proven (an image carrying
      gnupg+curl), cost is leaving netlab's default image, which a drift guard
      asserts on purpose. **Promote this one if any of the list gets picked up
      early:** since 2026-08-05 it is the single reason
      `examples/mixed-nos.yml` — the canonical every-NOS lab — does not deploy
      as-written on THIS host, so it is the only park that costs us something
      every time that lab is exercised.
    - **OpenBSD** — boots, authenticates and renders config now; hangs at
      `/tmp/config.sh` past 500s, most likely a pty expectation.
    - **Nokia SR-SIM** — the better long-term Nokia target (native container, no
      vrnetlab, which deletes the netem-vs-`mirred` risk), parked on being
      25.x-only and on an annual-subscription licence the container will not
      boot without.
    - **Extreme EXOS** and **`kind`** are DENIALS, not parks — the EXOS
      vrnetlab launcher wedges before sshd on both tested versions, and
      `k8s-kind` names its container outside clab's convention so the live-state
      merge cannot see it. Re-testing EXOS on a new release is fair game;
      `kind` needs a different mechanism, not a retry.

    **When picked up:** each platform runs the standing procedure in
    `docs/nos-sweep/admitting-a-platform.md` (probe → evidence in `results.md` →
    the up-to-five coordinated admission changes), against the **two bars**
    settled 2026-08-05 — a platform must work *and* its image must be one we may
    legitimately run.

### Post-v1.0 · jump-side DNS for lab nodes · **planned, after the v1.0 tag**

23. **Let `ssh -J twinlab-jump vyos@clab-<lab>-<node>` work without any
    per-lab client config.** Investigated 2026-08-06 against the live stack;
    the client-side half shipped the same day (below), the server-side half is
    this item.

    **What Twinlab loses today, precisely.** Three naming planes exist and only
    the third is broken. (1) Node→node inside the lab: netlab's
    `node_files/-shared-hosts` bind, working since the `LAB_FILES_DIR` fix.
    (2) Docker's embedded DNS on `<lab>_mgmt`, which already carries
    `DNSNames = [clab-<lab>-<node>, <short-id>, <node>]` → mgmt IP for free —
    but 127.0.0.11 answers only for networks the *querying* container is
    attached to, and the jump host is on the plain compose network.
    (3) containerlab's own `/etc/hosts` block, which IS still written — into
    the clab-api CONTAINER, where nothing reads it (verified: a deploy adds
    `###### CLAB-<lab>-START ######` there while the host's file stays
    untouched; clab-api runs `network_mode: host`, so docker seeded its hosts
    file as a copy of the host's at create time, which is why a stale block
    from an old direct-clab run appears in both). clab-api v0.5.0 ships no
    `containerlab` binary at all — it drives containerlab in-process as a
    library, so the write lands in its own mount namespace.

    **The constraint that decides the design, and the reason this is not a
    one-liner.** `permitopen` is a LITERAL string match — sshd(8): *"No pattern
    matching or name lookup is performed on the specified hostnames, they must
    be literal host names and/or addresses."* Proven end-to-end against the
    running jump: a request for the IP is permitted (`connect failed:
    Connection refused` — the alpine node has no sshd, so that IS the success
    signal); the same request by name is `administratively prohibited`; adding
    the name to the jump's `/etc/hosts` changes nothing; adding it to
    `permitopen` as well makes it permitted. So name-based access needs BOTH
    halves — resolution on the jump AND the literal name in
    `render_authorized_keys_line`.

    **Shape when picked up.** Backend feeds the jump a hosts fragment (a new
    `/internal/ssh/hosts` the lookup script refreshes, or a shared volume with
    a small refresher in the jump entrypoint), and the renderer emits
    `permitopen="clab-<lab>-<node>:*"` beside each IP. Costs: a doubled
    permitopen list, a staleness window between deploy and resolution, a new
    internal surface, and it touches the fail-safe authorized-keys renderer —
    the one place its module docstring says to keep exactly as it is. Attaching
    the jump to each lab's mgmt network would be strictly cleaner (docker DNS
    already has the names) but needs a Docker socket in the only
    internet-facing service: a hard no.

    **Rejected: bind-mounting the host's `/etc/hosts` into clab-api rw.** It
    would literally recover clab's block, but only for someone SSHing from the
    lab host, does nothing for the jump path, and lets a container mutate a
    host file — with that orphaned block as evidence of how the mutations leak.

    **Shipped instead (2026-08-06), and the reason this item is not urgent:**
    client-side aliases. `lib/ssh.ts` emits `Host <node>.<lab>` /
    `HostName <mgmt-ip>` / `ProxyJump twinlab-jump` blocks — per node in the
    Connect drawer, whole-lab in the Nodes tab's `LabSshConfigDialog` — so
    `ssh r1.mylab` works against an UNCHANGED backend: ProxyJump sends the
    resolved `HostName`, i.e. the IP, so the existing permitopen matches
    (verified). What this item adds over that is only the removal of the paste.
    Note also that mgmt IPs are already stable per lab (durable subnet +
    netlab-pinned node ids), so names buy readability, not stability.

### Post-v1.0 · config import for more source platforms · **planned, after the v1.0 tag**

24. **Widen config import beyond VyOS and IOS.** Research recorded 2026-08-11 in
    `docs/import-platforms-and-netlab-dependency.md`; the file-by-file procedure
    is `docs/adding-an-import-platform.md`.

    **Why this is cheap, and why it is strategically the right widening.** An
    imported lab's definition carries **no `module:` key at all** — the skeleton
    is `{provider, nodes, links}`, netlab generates only interface addressing,
    and every protocol line rides the carry verbatim. So import uses none of
    netlab's 654 config templates. Each platform added extends Twinlab's reach
    without adding a single netlab-template dependency, in the direction a
    declarative module system inherently cannot serve: somebody's actual
    production config.

    **Deployable and importable are independent axes, and only the intersection
    is a complete story.** VyOS is the only platform today where import →
    deploy → config-diff works end to end. FRR/routeros7/linux/bird/dnsmasq
    deploy but cannot be imported; IOL imports but was withdrawn on licensing,
    so an imported IOS lab is promised nothing. Widening the parser set past the
    deployable set manufactures more of the IOL situation.

    **Done first, 2026-08-11 (commit "config import: one platform table"):** the
    dispatch was four `device == "vyos"` ternaries whose `else` meant IOS, so a
    third platform would have been silently parsed and rewritten as Cisco rather
    than failing. `PlatformImporter` is now the single dispatch point and
    `split_buckets` reads a `ClassifySpec` instead of branching on device names.
    That work is **shipped**; what follows is the parsers.

    **Order.** (1) **FRR** — admitted, and its vtysh config is IOS-flavoured
    `"block"` form reusing machinery that exists; settle first whether
    `show running-config` or the per-daemon files are the better source.
    (2) **RouterOS 7** — admitted, `"flat"` form; `/export` line continuations
    need normalizing and its quarantine list is the least predictable of the
    three. (3) **Stop and decide** — every further candidate (EOS, NX-OS, Junos)
    is undeployable here.

    Rough sizes, reasoned from the two existing parsers rather than measured
    against a real dump: ~150–220 lines of parser each, 2–3 days per platform
    including a live config-diff proof. The first hour against a real
    `show running-config` would firm that up.

    **Ruled out, recorded so they are not re-derived:** cross-platform import
    (the carry is verbatim same-NOS config; crossing platforms means
    translation, which destroys the auditability that makes import
    trustworthy); Batfish as a universal parser (models rather than partitions,
    so the completeness invariant is lost — and a JVM service). **Structure-only
    import** — topology modeled, everything else quarantined, many platforms
    from one thin parser — is a legitimate alternative tier and a *product*
    decision: it trades the fidelity promise for breadth. Not planned.

### Operator documentation · **done 2026-08-11** (nine pages, served at `/docs`)

25. **`docs/guide/` — the operator guide.** The audience survey that opened this
    found one row empty: the person who runs Twinlab through the web UI has no
    document at all. Everything they need is written down *somewhere*, but as
    design records — `why`-documents for people changing the code. The Build
    tab is the sharpest case: its settings are explained only by the inline
    hints, which are reactive (they say why a control is greyed, not what it
    does).

    Nine pages: install · first lab · **the Build tab, setting by setting** ·
    operating · test suites · config import + templates · access and SSH ·
    troubleshooting **indexed by error slug** · definition reference. **ALL
    NINE WRITTEN 2026-08-11.**

    **Page 1 closed the largest gap the survey found.** Node-image acquisition
    was documented nowhere operator-facing: the root README covered only the
    VyOS digest pin, `e2e/README.md` added FRR and `python:alpine`, and CHR,
    bird and dnsmasq appeared in neither. The guide now carries the only
    complete per-platform table — pull, digest-pull-and-tag, `netlab clab
    build` inside the runner, or a vrnetlab build from a vendor download —
    with the trap that a vrnetlab build's tag is almost never the tag the
    catalog expects (live: the host has `mikrotik_routeros:7.16.2`, the
    catalog names `:7.21.4`), so such a node needs an explicit `image:`.
    Admitting or withdrawing a platform now edits that table too.

    It also closed the sizing question the outline had parked as
    unmeasurable, by measuring the running `mpls-l3vpn` lab: ~750 MB for the
    stack, ~350 MB per idle VyOS node, ~2.4 GB for the 7-node example.

    **Plan and conventions live in `docs/operator-guide-plan.md`, deliberately
    NOT in the guide** — writing rules, status and per-section source notes are
    authoring material, and a guide directory should hold only what a reader
    reads. That also means no skeleton page files: a page is created when it is
    written, so nobody clicks "Install" and gets notes-to-self.

    **Folded in deliberately:** the definition reference is the operator-facing
    half of `docs/definition-ownership.md`'s recommendation 3 — write the
    dialect down as a spec rather than leaving it spread across
    `find_unsupported_directives`, the PUT and prose. One page, both jobs.

    **Decided 2026-08-11:** no screenshots (no page needs one, and images are
    the highest-maintenance part of a guide) and no prose checker (the writing
    rules are the standard; a score invites chasing the number instead of
    reading the page). A **docs site served with the deployment** shipped
    the same day: the app renders the guide at `/docs` straight from
    `docs/guide/` (symlink into the frontend source + a `./docs:/docs:ro`
    mount), so the markdown keeps one home and the served documentation cannot
    drift from the running version. Two MIT dependencies, approved:
    `react-markdown` and `remark-gfm`. The route is deliberately OUTSIDE the
    auth gate — needing an account to read the troubleshooting page is
    backwards when signing in is what failed. **Not covered by the e2e suite
    yet.**

    **The binding writing rules:** concise and direct, no buzzwords, and
    **every setting names the definition key it writes** — that is what makes
    the page useful to someone who later edits the YAML by hand. Protocol
    semantics link to netlab rather than being re-taught; Twinlab does not
    fork the documentation of 654 templates. And every claim is verified
    against the code, not remembered from a design record — writing page 3
    turned up two UI facts no record carried (node names obey a STRICTER rule
    when typed than when loaded, since netlab splits the terse `a-b` link form
    on hyphens; config templates sit on a node's Advanced tab while "Save as
    template" is on General) and one outright error in the page's own first
    draft (`validate:` is not refused at PUT — only `tools:` and `tc:` are;
    `validate:` is merely unused because Twinlab runs its own suites).

    Deferred inside this item: a docs *site* (MkDocs Material, MIT) — packaging,
    pointless before the content exists; and in-app contextual help driven by a
    shared field-help map, which would keep UI and guide from drifting but is
    machinery to build only if the reference page proves hard to keep in sync.

### i18n · **deferred**

Internationalization is deferred project-wide, not just for the frontend rework
(where it was recorded as a non-goal): the UI is English-only, and no i18n
scaffolding (message catalogs, locale plumbing, translated content) should be
introduced until this is explicitly picked up.

### Deferred items from the API review (2026-07-23) · **deferred**

Surfaced while freezing the API shape for the Python client / black-box suite /
backend rework (`docs/twinlab_client_shape.py`); explicitly parked, not planned.
- **`GET /principals` enumeration exposure.** The grant-picker directory
  exposes every user and group name to ANY authenticated caller — including the
  zero-permission `user` role. Accepted for now (the tool is low-scale and
  collaborative); revisit if directory enumeration becomes a concern
  (options: require holding `lab:grant` somewhere, or search-only responses).
