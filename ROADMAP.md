# Twinlab Integration Roadmap

Planned integrations for deeper control and observability of running labs, drawing
on the `clab-api-server` v0.5.0 surface and `netlab`. This file is the durable
record of the agreed sequence, the grounded API facts behind it, and the
decisions already locked — so the plan survives context loss and implementation
doesn't need to re-research the endpoints.

Status legend: **planned** (agreed, not started) · **deferred** (explicitly
parked) · **candidate** (proposed, not yet decided).

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

**TODO (known gap, not yet built).** A backend crash *between* reserving a lab
(status `deploying`) and marking it `deployed` leaves the row stuck in `deploying`
with its subnet held. Fix: a startup reconciler that sweeps `deploying` rows —
mark `deployed` if clab-api shows the lab up, else release the reservation. Low
likelihood, cheap to add later; parked here so it isn't forgotten.

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
badge already marks a failed config).

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
