# Twinlab Integration Roadmap

Planned integrations for deeper control and observability of running labs, drawing
on the `clab-api-server` v0.5.0 surface and `netlab`. This file is the durable
record of the agreed sequence, the grounded API facts behind it, and the
decisions already locked — so the plan survives context loss and implementation
doesn't need to re-research the endpoints.

Status legend: **planned** (agreed, not started) · **deferred** (explicitly
parked) · **candidate** (proposed, not yet decided).

## Locked decisions

- **Phase 5 (packet capture + metrics stack) is deferred** — "to be defined
  later". Do not start without an explicit go-ahead and a scope decision (see the
  open question under Phase 5).
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

### Phase 1 — foundational backend · **planned**
3. **Per-lab mgmt subnet + concurrency.** Inject a distinct `addressing.mgmt.ipv4`
   (and `_network`) into each lab's definition — same mechanism as `set_lab_name`
   in `services/netlab.py`. Needs a subnet allocator that tracks used /24s
   (persist in the `labs` table) and picks a free one. Backend-only, no UI. This
   is what makes running several labs at once actually work, and it makes the
   Phase 0 SSH IPs correct per lab.

### Phase 2 — live UI substrate · **planned**
4. **Live events.** Backend consumes the clab-api `GET /api/v1/events` NDJSON
   stream and re-exposes it to the browser (SSE or WS) with our session auth;
   frontend consumer invalidates the relevant TanStack Query keys on events.
   Removes polling and makes pause/netem/terminal feel live. Not required by any
   feature, but high leverage, so it lands before the heavier ones.

### Phase 3 — testing-twin differentiator · **planned**
5. **Netem link impairment.** `tools/netem` set/show/reset. UI picks node +
   interface (the existing interface inventory populates the picker) and sets
   delay / jitter / loss / rate / corruption; show current state; reset. Keyed by
   container + interface. Self-contained, high product value for a testing twin.

### Phase 4 — big interactive lift · **planned**
6. **Web terminal.** Its own milestone: proxy the clab-api terminal-session
   WebSocket through FastAPI (auth handoff, base64 in/out framing, session
   lifecycle) and wire an xterm.js console in the frontend. Native WS path — no
   external tool.

### Phase 5 — heavy / external-dependency · **deferred (TBD later)**
7. **Packet capture** — Edgeshark packetflix or Wireshark-VNC. Needs new infra
   and an **OSI/Apache-2.0-compat licensing pass on Edgeshark** before committing.
8. **Metrics stack** — not served by clab-api; a separate build (e.g.
   Prometheus/Grafana/cAdvisor scraping the lab containers, or lightweight
   per-node CPU/mem/traffic straight from the Docker API). **Open scope question
   to resolve when this is picked up:** full observability stack vs. lightweight
   Docker-API stats.

## Candidate (not committed)

- **`netlab validate`** — run the topology's own test assertions against the live
  lab. Strong fit for the "validate before prod" testing mission and reachable
  from the `netlab create` snapshot without `netlab up`. Proposed as a future
  addition; decide whether to fold it in.
