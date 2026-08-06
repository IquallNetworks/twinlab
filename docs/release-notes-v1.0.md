# Twinlab v1.0 — release notes (DRAFT)

**Status: draft for maintainer review.** Nothing here is published, tagged or pushed. Four
decisions are still open and this document assumes none of them (ROADMAP item 22): the PyPI
account and whether to use trusted publishing; whether the stack carries a version number
distinct from the client's; whether a `CHANGELOG.md` is introduced (in which case this file is
its first entry); and whether the tag is cut on `dev` or after a merge to `main`.

---

## What Twinlab is

Twinlab generates reproducible simulated network topologies from a declarative definition. It is
a layer on top of [Containerlab](https://containerlab.dev/), driven through
[netlab](https://netlab.tools/), that lets engineers describe network nodes, links, services and
test scenarios declaratively, then deploys reproducible lab environments from that definition —
for validating configurations, orchestration workflows, service provisioning and operational
procedures before they touch production.

v1.0 is the first release with a settled API contract. The definition is the sole source of
truth for a lab, and the same definition always produces the same environment.

## What is in v1.0

**A settled HTTP/WebSocket API.** `docs/twinlab_client_shape.py` is the reviewed contract; the
backend implements it in full (twenty-six reviewed deltas). Every non-2xx response wears one
error envelope — `{code, message, extras}` — with stable code slugs.

**A split lab lifecycle: create → author → deploy.** `POST /labs` creates a bare record and
reserves the lab's management `/24` up front; `PUT /labs/{name}` authors or replaces the stored
definition, validated by a dry `netlab create`; `POST /labs/{name}/deploy` is the only deploy
verb. A lab is a durable record: it survives destroy and is redeployable from the same
definition, and the caller never resupplies the definition, suites or templates.

**Long operations are async jobs.** Deploy, configure, destroy and suite runs return `202` with a
running job; callers poll or watch the SSE stream. One running job per lab is the operation
mutex — a concurrent submit of any kind is a `409 job_in_flight`. Jobs persist, list per-lab and
across the fleet, and survive a backend restart as an honest failure rather than a wedged lab.

**Runtime control and observability** over live lab state: per-node and whole-lab power, config
save, container logs, an interface inventory, a logical link table with live operational state,
netem link impairment keyed by node and interface, and batch runtime actions that stage a whole
degraded condition in one request. A Server-Sent Events stream carries container and job events,
filtered to the caller's readable labs; a WebSocket serves an interactive node terminal.

**Declarative validation.** Test suites are stored on the lab record and run as a
render → execute → parse → assert pipeline — all data, no user code. Commands and expectations
are Jinja2 templates rendered per node against a pinned fact namespace derived from netlab's
expanded topology. Parsing is JSON or TextFSM; assertions are substring, regex, or a structured
`compare` over parsed data. Suites gate a config push (`config-time`) or run on demand.

**Two input methods beyond hand-authoring.** A template library serves built-in network
templates alongside labs published from the fleet, plus reusable node fragments. Config import
turns real device configurations into a twin: per-platform parsers, caller-declared wiring,
pinned addressing, a source-interface → lab-interface map, verbatim carry of everything not
modeled, and quarantine for what must not be applied — with every source line landing in exactly
one of modeled, carried or quarantined. A stateless config-diff proves fidelity against a
running lab.

**A web frontend** over the same contract: a role-aware dashboard, routed lab tabs, a guided
visual topology builder with a full-syntax text escape hatch, a live topology canvas, a jobs
center, per-node connect and terminal surfaces, and an account page covering passwords, API keys
and SSH keys.

**Authentication and scoped RBAC.** Two credentials — opaque session cookies and Bearer API keys
— resolved by one shared path across HTTP routes, the event stream and the terminal handshake.
Permissions are lab-scoped (read, edit, configure, validate, terminal, destroy, grant) plus
global ones (lab creation, user, group and template management), granted to users or groups.

**An SSH jump host.** Stock OpenSSH resolving per-key access live against the backend, so
revoking a key, a grant or a user bites on the next connection. Users reach lab nodes with plain
`ssh -J`, which makes a deployed lab Ansible-ready.

**Host preparation** is isolated in one minimal sidecar — the only component allowed to touch
host network devices — so multi-access LAN topologies deploy end to end without the rest of the
stack holding host network privileges.

### Supported NOS platforms

VyOS, FRR and MikroTik RouterOS 7 (CHR), plus the bird and dnsmasq daemons and `linux` as the
host/endpoint device. This is the *tested* set, not a wish list: `examples/mixed-nos.yml` stands
all six up in one lab, reaches OSPF Full on every cross-vendor pairing and forwards end to end,
and its suite asserts it. A definition naming another netlab device still edits and may still
deploy — nothing about it is promised.

## The client package

`twinlab-client` is the distributable artifact: a typed, asyncio client for the whole API.
Every wire shape is a frozen dataclass, every method a coroutine, and any non-2xx response
raises `TwinlabApiError` carrying the envelope. It ships `py.typed` and is Apache-2.0.

The stack itself is not distributed — Twinlab is deployed from this repository with
`docker compose`.

## What backs the release

- Backend, client, netlab-runner and hostprep: `ruff format` + `ruff check` + basedpyright
  (strict) + pytest — 371 tests.
- Frontend: `pnpm typecheck` + `pnpm build` + `pnpm check:build-doc` (90 parser/emitter
  round-trip and gate checks).
- **`blackbox/`** — the contract's enforcement: 148 tests exercising a live stack through the
  client only, including real containerlab deploys.
- **`e2e/`** — the browser layer's: 51 Playwright specs driving the real frontend against a
  dedicated stack that every run resets to an empty backend, deploying, operating and destroying
  a real multi-vendor lab.

## Explicitly not in v1.0

Packet capture and metrics; scenario orchestration beyond batch runtime actions; validation-gate
parallelization; i18n. Cisco IOL is deliberately **not** an admitted platform — it works, but its
only legitimate image source is Cisco's CML reference-platform set, which is licensed for use
inside CML only; revisiting that is a post-v1.0 item. Nokia SR Linux is proven on a parallel
branch but its runner plumbing has never landed here.

## Requirements

A Linux host — Twinlab's lab layer drives Linux kernel networking directly and is not designed
for anything else. Docker with `docker compose`, a host user in the `clab_api` group, and the
node images for the platforms you intend to use (images are used, never distributed).
