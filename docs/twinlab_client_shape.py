"""Shape sketch of the Twinlab Python client (`TwinlabClient`) — FOR REVIEW.

A contract sketch, not an implementation. The sketch shows the **target
contract**: approved/agreed proposals are APPLIED to the shapes and methods,
with the current wire (commit bc89daa) noted inline where it differs — those
notes are the backend-rework checklist. Markers:

- ``QUIRK:``    — current behavior the client/tests must handle.
- ``PROPOSAL:`` — a change for the backend rework. ``(APPROVED)`` = agreed and
  applied here; ``(DISCUSS)`` = agreed in principle, shape drafted for review.
- ``TODO:``     — reviewer notes, pending decision.

Deltas from today's wire, applied below (= the backend rework checklist):

1. Unified error envelope (`TwinlabApiError`).
2. Lifecycle split: ``POST /labs`` = create-only record; ``POST
   /labs/{name}/deploy`` (today's redeploy, renamed) is the only deploy verb,
   guarded by the deploying-status mutex (409); `LabStatus` gains "created".
3. Status vocabularies pinned as Literals; container state normalized.
4. New endpoints: users get/delete/password-reset/activate-toggle, self
   password change, groups get, API keys (create/list/revoke) + Bearer auth.
5. DELETE /users refuses removing the last admin (409).
6. ``GET /labs/{name}/interfaces`` keys nodes by SHORT node name (backend
   translates from the container name).
7. Netem: durations are structured ``{value, unit}`` pairs (not "50ms"
   strings); ``set`` has REPLACE semantics (omitted dimension = cleared, empty
   call = clear all), subsuming the dropped ``/netem/reset`` endpoint.
8. ``PUT /labs/{name}/owner`` returns its own ``LabOwner`` model, not a fake
   Grant.
9. A config push that ran but failed on >=1 node is a 2xx
   ``status="config_failed"`` with per-node results — no longer an HTTP 502.
10. Per-lab ``permissions`` (LabSummary/LabDetail) is MASKED to the seven
    lab-scoped permissions — global-only perms (lab:create, user:manage,
    group:manage) never appear there (they ride on ``/auth/me``).
11. ``DELETE /labs/{name}`` with remove=false on a not-running lab is a 409
    (wire today: 404) — 404 stays reserved for existence-hiding; and
    remove=true RELEASES the lab's mgmt-subnet reservation (a plain
    "destroyed" record keeps its subnet, so a redeploy reproduces the same
    environment).
12. Async job model (APPROVED 2026-07-29; shapes drafted for review): the
    four long operations — deploy, configure, destroy, suite run — return
    **202 + a running ``Job``** and do the work server-side; callers poll
    ``GET /labs/{name}/jobs/{id}`` (wire today: synchronous long calls that
    return the result body directly). Pre-accept checks stay synchronous
    (existence-hiding 404, 409 no_definition / lab_not_running, suite 404).
    ONE running job per lab, any kind — a concurrent submit is 409
    ``job_in_flight`` (subsumes delta 2's deploy mutex; configure/destroy/
    suite runs, unguarded today, gain it too). Finished jobs persist as
    recent history. Completion is discovered by POLLING only; job events on
    the SSE stream are deferred (recorded in ROADMAP).
13. External SSH access (APPROVED 2026-07-29; shapes drafted for review):
    users register SSH PUBLIC keys (``/auth/ssh-keys``, self-service like
    API keys), and a stack-owned OpenSSH jump host lets a key's owner tunnel
    — plain ``ssh -J``, Ansible-ready — to ALL TCP ports of nodes in labs
    where they hold ``lab:terminal``, authorization re-evaluated from live
    RBAC on every new connection. ``lab:terminal`` now means "interactive
    node access" (web terminal AND SSH jump — no catalog change). ``GET
    /ssh-access`` advertises the jump address. Besides bring-your-own-key,
    ``POST /auth/ssh-keys/generate`` creates an ed25519 pair server-side,
    registers the public half, and returns the private key ONCE (never
    stored — the api-key pattern). (wire today: no ssh-key surface, no jump
    service.)
14. Link table (APPROVED 2026-07-30): ``GET
    /labs/{name}/links`` serves the lab's LOGICAL link table, derived from
    the netlab-expanded topology (a LAN is one link with N endpoints, not
    clab.yml's per-member fan-out): per link the netlab ``linkindex``,
    type, prefix, and per-endpoint ``node``/``interface``/IPs — plus a
    DERIVED per-link oper state rolled up from the live interface
    inventory and each endpoint's ACTIVE netem impairment (one read serves
    the whole link view; per-node ``show_netem`` remains for the node
    view). The table is produced by the same dry ``netlab create`` that
    validates a PUT and persisted on the lab record, so reads never pay the
    subprocess cost; it works on any AUTHORED lab (undeployed = full table,
    states unknown). 409 ``no_definition`` on a bare created record. (wire
    today: no link surface — the frontend guesses links from the raw
    definition and the netem tests guess interface names.)
15. Cross-lab job listing (APPROVED 2026-07-30): ``GET /jobs`` serves recent
    jobs across every lab the caller may read, newest first — the view the
    per-lab ``GET /labs/{name}/jobs`` cannot give. Any authenticated user,
    filtered per lab like ``/events`` (a global ``lab:read`` sees all);
    ``?limit=`` (default 20, max 200). Same ``Job`` shape, which already
    carries ``lab_name``. Jobs of SOFT-DELETED labs are EXCLUDED, so a
    destroy-with-remove job leaves the fleet list when its lab does — its
    terminal state is read by id through the per-lab route, which stays
    readable on a removed lab (delta 12). (wire today: no cross-lab route —
    the frontend fans one query out per lab and merges client-side.)
16. Job events on the SSE stream (APPROVED 2026-07-30): ``GET /events`` gains
    job lifecycle events, so job completion no longer has to be discovered by
    polling (this LIFTS the deferral recorded in delta 12). Events become
    NAMED: ``event: lab`` for today's container-lifecycle payload,
    ``event: job`` for the new ``JobEvent`` — a poke carrying
    ``{lab, job_id, kind, status, timestamp}`` and NOT the job's
    result/error, which the caller reads with ``get_job``. One event when a
    job is submitted (status "running") and one when it reaches a terminal
    state. Filtered by the same readable-lab set as lab events. There is no
    replay (no Last-Event-ID), so a reconnect can miss events and consumers
    keep a slow fallback poll. (wire today: every event is unnamed — a
    default-``message`` container event; naming them is the breaking part of
    this delta.)
17. Test-suites v2 (APPROVED 2026-08-03): the validation pipeline becomes
    **render → execute → parse → assert**, all still declarative data — no
    user code. Commands and expected values may carry Jinja2 templates
    rendered per node against facts from the netlab-expanded topology
    (``{{ nodes.pe4.loopback.ipv4 | address }}``), replacing the
    hardcoded-IP suites that broke on every re-address; rendering is
    sandboxed with strict undefined. The fact namespace starts as netlab's
    RAW node data — PROVISIONAL, deliberately unpinned; a pinned subset is
    a decision to make before v1.0 — and is discoverable via the new ``GET
    /labs/{name}/facts`` endpoint (which also insulates consumers from the
    future pinning). A test's action becomes a per-device CASE (``run`` =
    one ``TestCase`` or a device-keyed dict; case-level keying chosen over
    netlab-style field-level — one atomic recipe per device, no
    key-consistency rules) so one suite serves VyOS and IOL; a node whose
    device has no case reports "skip" (the reserved status, now used). A
    case may declare ``parse`` ("json" | "textfsm") turning stdout into
    structured data asserted with ``compare`` — napalm-validate's grammar
    (nested partial match, strict mode, numeric operators, ranges) — while
    the raw matchers (contains/not_contains/matches) remain for unparsed
    output; json_path/equals are RETIRED (a dotted path is the degenerate
    compare spec; NO stored-suite migration — dev-phase, no real-world
    data; the repo examples are rewritten to v2). ``interactive: true``
    routes a case through a persistent CLI channel where the node's
    transport is SSH — IOS truncates timed commands (``ping … repeat``,
    ``traceroute``) on a one-shot exec channel — and is a deliberate no-op
    over docker exec, which already captures everything. (wire today: one
    command string per test, raw + json_path matchers only, no rendering,
    no parse stage, no interactive mode, no facts endpoint.)

Conventions:

- Base path ``/api/v1``; OpenAPI at ``openapi.json`` (schema-check the real
  client against it in CI).
- Auth: opaque HttpOnly session cookie from ``login`` (the client carries a
  cookie jar), OR an API key passed at construction — the desired client shape;
  server-side API-key support is PROPOSED (not served yet, see the Auth
  section). Everything except login/health needs one of the two.
- Lab-guarded routes: **404** when the caller can't read the lab (existence
  hidden), **403** when readable but lacking the specific permission.
- Names (lab/node/suite): ``^[A-Za-z0-9][A-Za-z0-9_.-]*$``, max 64.
- **Async client**: every method is a coroutine (httpx.AsyncClient +
  `websockets`); the client is an async context manager.
- Ids are UUIDs — **UUIDv7** (decided 2026-07-28: the backend bumps to
  Python 3.14 and uses stdlib `uuid.uuid7`; wire today: v4). Applies to every
  id field below.
- Unordered unique collections (roles, permissions, scopes) are `set` in the
  client; the wire is a JSON array either way.

PROPOSAL (APPROVED — shape at `TwinlabApiError`): unify the error envelope.
Today `detail` has four shapes (labs/grants {stage, message, ...},
users/groups {reason, detail}, login a bare string, FastAPI's 422 list).

PROPOSAL (APPROVED — shapes in the Auth/Users/Groups sections, marked
PROPOSED): missing endpoints — get/delete user, admin password reset,
activate toggle, self password change, get group, API keys.
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


# Not frozen (implementation finding): re-raising through a context manager
# assigns `exc.__traceback__` at Python level (contextlib), which a frozen
# dataclass's __setattr__ rejects — exceptions must stay mutable.
@dataclass(slots=True)
class TwinlabApiError(Exception):
    """Any non-2xx response.

    PROPOSED SHAPE (APPROVED): the rework serves ONE envelope for every error,
    via a single exception handler:

        {"code": "<machine slug>", "message": "<human>", "extras": {...}}

    - `code`: stable slug for programmatic matching — e.g. "lab_not_found",
      "netlab_invalid", "config_push_failed", "username_taken",
      "mgmt_subnet_exhausted", "upstream_error", "not_authenticated",
      "permission_denied", "validation_error".
    - `extras`: endpoint-specific payload (netlab `stderr`, per-node config
      results, FastAPI field errors under "errors", ...).

    Until the backend lands it, the client fills these fields best-effort from
    the four current shapes (`code` from `stage`/`reason` when present, else
    "unknown"; raw body kept in `extras["raw"]`).
    """

    status_code: int
    code: str
    message: str
    extras: dict[str, object]


# --------------------------------------------------------------------------- #
# Auth / identity shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UserInfo:
    """`GET /auth/me` / login response. GLOBAL roles/permissions only —
    per-lab permissions ride on each lab payload."""

    username: str
    roles: set[str]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class UserSummary:
    """One user (`/users`). `roles` = global roles."""

    id: UUID
    username: str
    is_active: bool
    roles: set[str]


@dataclass(frozen=True, slots=True)
class GroupMember:
    id: UUID
    username: str


@dataclass(frozen=True, slots=True)
class GroupSummary:
    """Admin-defined user group; members inherit its global roles and lab grants."""

    id: UUID
    name: str
    description: str
    members: list[GroupMember]
    roles: set[str]  # global roles bound to the group


@dataclass(frozen=True, slots=True)
class Role:
    """One catalog role (`GET /roles`) — never hardcode the role list."""

    name: str
    scopes: set[Literal["global", "lab"]]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class ApiKey:
    """PROPOSED (APPROVED, not served yet): one API key, as listings show
    it — never the secret."""

    id: UUID
    name: str  # caller-chosen label, e.g. "ci"
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApiKeyCreated:
    """PROPOSED (APPROVED): create response — the only time the secret is returned."""

    key: str  # the bearer secret, e.g. "tl_<random>"; shown once, stored hashed
    info: ApiKey


@dataclass(frozen=True, slots=True)
class SshKey:
    """One registered SSH public key (`/auth/ssh-keys`) — delta 13.

    Registering a key unlocks the stack's SSH jump host for its owner (see
    the SSH-keys client section for the connection semantics). Nothing here
    is secret — the user keeps the private key — so create returns this same
    shape (no `SshKeyCreated` analogue)."""

    id: UUID
    name: str  # caller-chosen label, unique per user, e.g. "laptop"
    algorithm: str  # e.g. "ssh-ed25519"
    fingerprint: str  # "SHA256:<43 base64 chars>" — what `ssh-keygen -lf` prints
    comment: str | None  # trailing comment of the registered line, display only
    created_at: datetime
    last_used_at: datetime | None  # last OFFERED at the jump, not last node login


@dataclass(frozen=True, slots=True)
class SshKeyGenerated:
    """`POST /auth/ssh-keys/generate` response — the only time the private
    key exists outside the caller's hands. The server registers the public
    half and DISCARDS the private half (no escrow); losing it means
    generating a new key."""

    private_key: str  # OpenSSH PEM text; write to a file with mode 0600
    info: SshKey


@dataclass(frozen=True, slots=True)
class SshAccess:
    """`GET /ssh-access` — the jump-host coordinates (delta 13).

    `enabled` False (deployment has no jump configured) leaves the rest None.
    Usage: ``ssh -o ProxyJump={user}@{host}:{port} <node-user>@<node-mgmt-ip>``
    — node mgmt IPs ride on `LabNodeState.mgmt_ip`; the node's own login is
    unchanged (the tunnel only grants reachability)."""

    enabled: bool
    host: str | None
    port: int | None
    user: str | None  # the jump account name, e.g. "jump"


@dataclass(frozen=True, slots=True)
class Principal:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class LabOwner:
    """`PUT /labs/{name}/owner` response (APPROVED — wire today reuses the
    grant shape with the LAB's UUID as `id` and the non-catalog role "owner")."""

    lab: str
    owner: Principal


@dataclass(frozen=True, slots=True)
class Principals:
    """`GET /principals`: id+name of all users/groups, for grantors lacking
    user:manage / group:manage."""

    users: list[Principal]
    groups: list[Principal]


@dataclass(frozen=True, slots=True)
class Grant:
    """One lab-scoped role binding. `principal_name` is None if the principal
    no longer exists.

    (answered: "why does it survive?") It isn't a designed lifecycle: deleting
    a GROUP does cascade its bindings, and users can't be deleted through the
    API at all today — so a dangling principal only occurs via out-of-band DB
    edits, and the None branch is defensive. Once `delete_user` (PROPOSED
    below) lands with binding cascade, `principal_name` can become required.
    """

    id: UUID
    principal_type: Literal["user", "group"]
    principal_id: UUID
    principal_name: str | None
    role: str


# --------------------------------------------------------------------------- #
# Health shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Liveness:
    status: Literal["ok"]


@dataclass(frozen=True, slots=True)
class Readiness:
    """`GET /health/ready` — same body on 200 and 503 (degraded is data)."""

    status: Literal["ready", "degraded"]
    # Value is "ok" or the failure message — `Literal["ok"] | str` collapses to
    # `str`, so the union isn't expressible as a type. PROPOSAL: per-check
    # {ok: bool, detail: str} so health is typed, not sentinel-string.
    checks: dict[str, str]


# --------------------------------------------------------------------------- #
# Lab shapes
# --------------------------------------------------------------------------- #

# PROPOSAL (APPROVED): pin these as Literals in the backend response models so
# OpenAPI carries them. "created" is new with the lifecycle split (a record
# that has never been deployed); the rest exist on the wire today.
LabStatus = Literal["created", "deploying", "deployed", "destroyed"]
DeployStatus = Literal["deployed", "configured", "config_failed", "validation_failed"]
ConfigureStatus = Literal["configured", "config_failed", "validation_failed"]
# APPROVED (replaces `config_time_ok: bool | None` on the wire). No "skipped"
# state on purpose: a skipped gate RETAINS the previous result (skipping a
# configure must not erase a known-red gate); "no config-time suites" = "not_run".
ConfigTimeStatus = Literal["not_run", "passed", "failed"]

# Configure failure layers (APPROVED — layer 2 changes from today's wire):
#   1. The push could not run at all (runner down, definition rejected)
#      -> HTTP 422/502, no per-node data. An HTTP error: nothing ran.
#   2. The push ran but >=1 node failed its Ansible play -> 2xx
#      status="config_failed" with `configuration` carrying the per-node
#      results (validation is None — the gate doesn't run on a failed push).
#      Wire today: HTTP 502 with the results buried in the error detail.
#   3. The push succeeded everywhere but the config-time gate failed -> 2xx
#      status="validation_failed".
# Rule of thumb: HTTP errors mean "could not run"; if it ran, the outcome —
# good or bad — is data.

# TODO(state) -> PROPOSAL: pin to docker-engine's vocabulary. Today the value
# is a clab-api passthrough, so the backend must normalize/validate it as part
# of the same rework; until then the client should tolerate unknown strings.
ContainerState = Literal[
    "created", "running", "paused", "restarting", "removing", "exited", "dead"
]


@dataclass(frozen=True, slots=True)
class LabNodeState:
    """Live per-node state from clab-api (best-effort)."""

    name: str  # short node name, e.g. "r1"
    container: str  # "clab-<lab>-<node>"
    image: str
    state: ContainerState  # requires the backend pin above
    mgmt_ip: str  # bare IP (CIDR stripped); "" when none


# (decided 2026-07-28: NO Summary/Detail split for v1.0 — Detail is already
# Summary + definition + node list; revisit with the frontend rework if a
# leaner shape proves wanted.)
@dataclass(frozen=True, slots=True)
class LabSummary:
    """One row of `GET /labs`. `status` is the durable record. `nodes` counts
    the containers PRESENT in live state (any state; 0 when down or clab-api
    unreachable) and `nodes_running` the subset actually running (APPROVED
    2026-07-29: both data points — after a host reboot a lab can be
    present-but-exited, e.g. 7/0). `permissions` = caller's effective set on
    THIS lab (global ∪ grants ∪ owner-implicit), MASKED to the lab-scoped
    permission set (APPROVED — global-only perms never appear here; see
    /auth/me for those)."""

    name: str
    status: LabStatus
    owner: Principal | None  # APPROVED — wire today: bare username string
    created_at: datetime
    updated_at: datetime
    nodes: int
    nodes_running: int
    config_time_status: (
        ConfigTimeStatus  # APPROVED — wire today: config_time_ok: bool | None
    )
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class LabDetail:  # No Summary/Detail split for v1.0 (see LabSummary note).
    """`GET /labs/{name}`: stored record + live nodes. `definition` is the
    lab's source of truth — None until authored (a "created" lab)."""

    name: str
    status: LabStatus
    definition: str | None  # None only while status="created" (lifecycle split)
    owner: Principal | None  # APPROVED — wire today: bare username string
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]
    config_time_status: ConfigTimeStatus  # APPROVED — wire today: config_time_ok
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class NodeConfigResult:
    """Per-node outcome of a config push (from Ansible's PLAY RECAP)."""

    node: str
    status: Literal["configured", "failed"]  # PROPOSAL (APPROVED): pinned
    changed: int
    failed: int


@dataclass(frozen=True, slots=True)
class DeployResponse:
    """Terminal `result` of a deploy Job (delta 12 — wire today: the body of
    the synchronous `POST /labs/{name}/deploy`).

    - bare deploy:               status="deployed", configuration/validation None
    - +configure, gate ok:       status="configured" (validation None if skipped
      or no config-time suites)
    - +configure, push failed:   status="config_failed" — configuration carries
      the per-node results, validation None (gate not run)
    - +configure, gate failed:   status="validation_failed"
    All four are job SUCCESSES: a *failed* job means the operation could not
    run at all (`Job.error` carries the envelope).
    """

    status: DeployStatus
    lab_name: str
    nodes: list[str]  # short node names
    configuration: list[NodeConfigResult] | None
    validation: list["SuiteReport"] | None


@dataclass(frozen=True, slots=True)
class ConfigureResponse:
    """Terminal `result` of a configure Job. Like DeployResponse, but
    `configuration` is always present (a push that couldn't run FAILS the
    job instead)."""

    status: ConfigureStatus
    lab_name: str
    configuration: list[NodeConfigResult]
    validation: list["SuiteReport"] | None


@dataclass(frozen=True, slots=True)
class DestroyResponse:
    """Terminal `result` of a destroy Job. "destroyed" = record kept,
    redeployable; "deleted" = remove=true, record soft-deleted."""

    status: Literal["destroyed", "deleted"]  # PROPOSAL (APPROVED): pinned
    detail: str  # containerlab teardown output, or "lab was not running"


@dataclass(frozen=True, slots=True)
class LabActionResponse:
    """Power/netem action result: clab-api's message, verbatim. A 2xx IS the
    outcome; the message is decoration."""

    message: str


@dataclass(frozen=True, slots=True)
class SaveConfigResponse:
    message: str
    output: str  # per-node save output from containerlab


@dataclass(frozen=True, slots=True)
class NodeLogsResponse:
    node: str  # short node name (echoed from the path)
    container: str
    logs: str


@dataclass(frozen=True, slots=True)
class NodeInterface:
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str  # clab-api's interface `type`


@dataclass(frozen=True, slots=True)
class NodeInterfaces:
    """One node's interface inventory.

    APPROVED: `node` is the SHORT node name (backend translates) — wire today:
    the container name ("clab-<lab>-<node>"), a clab-api passthrough."""

    node: str
    interfaces: list[NodeInterface]


@dataclass(frozen=True, slots=True)
class Duration:
    """A netem duration as a structured {value, unit} pair (APPROVED — wire
    today: strings like "50ms"). The author's unit choice is preserved."""

    value: float
    unit: Literal["us", "ms", "s"]


@dataclass(frozen=True, slots=True)
class NetemImpairment:
    """Current netem shaping on one interface. None / 0 = that dimension
    unshaped."""

    interface: str
    delay: Duration | None
    jitter: Duration | None
    loss: float  # percent
    rate: int  # kbit/s
    corruption: float  # percent


# Delta 14 (APPROVED 2026-07-30). Pinned as a Literal — unlike the interface `state`
# passthrough — because Twinlab DERIVES this value itself. Roll-up over the
# link's endpoint states: all "up" -> "up"; all known-not-up -> "down"; a mix
# of known states -> "degraded" (a p2p with one side down reads degraded — the
# per-endpoint states disambiguate; in practice a veth pair drops both sides);
# any endpoint unknown (lab not deployed, inventory unavailable, interface not
# found) -> "unknown".
LinkOperState = Literal["up", "degraded", "down", "unknown"]


@dataclass(frozen=True, slots=True)
class LinkEndpoint:
    """One attachment point of a logical link (delta 14)."""

    node: str  # SHORT node name — matches /interfaces keys and the netem routes
    # The container-side interface name: what /interfaces reports and netem
    # accepts. QUIRK: resolved against the live inventory (name-or-alias
    # match) when the lab is deployed; undeployed it is the generated
    # clab-side name — identical for every non-renaming kind, but a renaming
    # kind (cisco IOL: "Ethernet0/1" vs "eth1") only settles once deployed.
    interface: str
    ifname: (
        str  # netlab/NOS-side name (e.g. "Ethernet0/1"); == interface when they agree
    )
    ifindex: int  # netlab interface index
    ipv4: str | None  # netlab-assigned CIDR; None on unnumbered/L2-only links
    ipv6: str | None
    # Live oper state passthrough for this interface ("up"/"down"/... — the
    # same unpinned vocabulary QUIRK as NodeInterface.state); None = unknown.
    state: str | None
    # Active netem impairment on this interface (reuses NetemImpairment — its
    # `interface` field is redundant here but keeps one shape). None = not
    # impaired OR unknown: only meaningful on a live read (`LabLinks.live`).
    # Deliberately NOT folded into oper_state — an impairment is requested
    # behavior, not degraded health; the UI renders them as distinct signals.
    impairment: NetemImpairment | None


@dataclass(frozen=True, slots=True)
class LabLink:
    """One LOGICAL link from the netlab-expanded topology (delta 14):
    a LAN is ONE link with N endpoints, stubs/loopbacks have one — not
    clab.yml's physical per-member fan-out."""

    index: int  # netlab linkindex — stable within a definition version
    name: str | None  # user-set link name only (netlab's _linkname is internal)
    # netlab's link type ("p2p" | "lan" | "stub" | "loopback" observed) — a
    # passthrough str, not pinned: netlab owns the vocabulary. QUIRK: not a
    # rendering signal — a linux-host p2p comes out "lan" (bridge-backed);
    # discriminate on len(endpoints) instead.
    type: str
    prefix_ipv4: str | None  # the link subnet; the only IP surface we have
    prefix_ipv6: str | None  # (/interfaces is L2-only)
    bandwidth: int | None  # netlab passthrough, as authored
    mtu: int | None
    oper_state: LinkOperState
    endpoints: list[LinkEndpoint]


@dataclass(frozen=True, slots=True)
class LabLinks:
    """The lab's link table (delta 14).

    `live` is the honesty flag: False means oper state could not be resolved
    (lab not deployed, or the interface inventory was unavailable) and every
    state is "unknown" — distinguishable from a deployed lab reporting real
    unknowns."""

    links: list[LabLink]
    live: bool


@dataclass(frozen=True, slots=True)
class LabEvent:
    """One container-lifecycle payload from `GET /events`.

    PROPOSAL (delta 16, APPROVED): carried by the NAMED SSE event ``lab``
    (wire today: the unnamed default event)."""

    lab: str
    node: str | None
    action: str  # "create" | "start" | "stop" | "kill" | "die" | "destroy" | ...
    timestamp: str


# The other `GET /events` payload, `JobEvent`, is PROPOSED in the Job shapes
# section below (it is typed by JobKind/JobStatus, defined there).


# --------------------------------------------------------------------------- #
# Test-suite shapes (v2 — delta 17, APPROVED 2026-08-03)
# --------------------------------------------------------------------------- #

ParseMode = Literal["json", "textfsm"]
# How a case turns stdout into data `compare` can assert on:
# - "json": stdout must parse as JSON. On VyOS this costs nothing — FRR's
#   `vtysh -c "show ... json"` emits it natively (verified live on OSPF
#   neighbor / LDP neighbor / BGP VPNv4 summary), so routing-state gates
#   need no template layer at all.
# - "textfsm": stdout is parsed into a list of records via TextFSM — the
#   template resolved from the node's DEVICE plus the rendered command,
#   out of ntc-templates' library (cisco_ios: 143 templates) overlaid by
#   Twinlab-packaged templates (e.g. our own `show mpls ldp neighbor` for
#   cisco_ios, which ntc lacks).
# A missing template or a failed parse is an "error" result — NEVER a
# silent raw-string fallback (netmiko's use_textfsm footgun, deliberately
# excluded).


@dataclass(frozen=True, slots=True)
class TestExpectation:
    """Exactly ONE of contains/not_contains/matches/compare (server-checked).

    The raw matchers pair with unparsed stdout; `compare` REQUIRES the case
    to declare `parse` — and vice versa (server-checked both ways). It
    asserts over the parsed data with napalm-validate's grammar (Apache-2.0,
    `napalm.base.validate.compare`): nested partial match by default,
    ``_mode: strict`` for exhaustiveness, numeric operators (``"<15"``,
    ranges ``"10<->20"``, percent tolerance), list semantics. A compare spec
    is DATA — still no expression eval anywhere.

    APPROVED (delta 17): json_path/equals RETIRED — a dotted path is the
    degenerate nested compare spec. No stored-suite migration (dev-phase,
    no real-world data); the repo's example suites are rewritten to v2."""

    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None  # regex, re.search on stdout
    compare: dict[str, object] | None = None  # napalm-validate spec, see above


@dataclass(frozen=True, slots=True)
class TestCase:
    """What actually runs on a node: one command and how to judge its output.

    `command` — and every string inside `expect` — may carry Jinja2
    ``{{ ... }}`` rendered per executing node against the fact namespace:
    ``node`` (the executing node) and ``nodes.<name>`` (any node), each
    exposing that node's data from the netlab-expanded topology (the same
    artifact behind the link table) — e.g. ``loopback.ipv4``, ``mgmt.ipv4``,
    ``interfaces[].{ifname, ipv4, neighbors}``, ``vrfs.<vrf>.loopback`` —
    plus one filter ``address`` stripping a CIDR's prefix length
    ("10.0.0.5/32" → "10.0.0.5"). APPROVED (delta 17): the namespace is
    netlab's RAW node dict for now — PROVISIONAL and deliberately unpinned
    (netlab-shaped, may drift across netlab versions); pinning a stable
    subset is a decision to make BEFORE v1.0. Inspect it with `facts()`.
    Rendering is SANDBOXED (jinja2 SandboxedEnvironment, no attribute
    escapes) with StrictUndefined: at PUT, templates are always
    syntax-checked and — when the lab has a definition, so facts exist —
    dry-rendered, either failure a 422 ``template_invalid``; a render
    failure at run time (suite authored before the definition, later
    drifted) is that check's "error" result, never a crashed job.

    `interactive` routes the exec through a persistent CLI channel when the
    node's transport is SSH (a no-op over docker exec): IOS closes a
    one-shot exec channel on timed commands (``ping ... repeat``,
    ``traceroute``), truncating output after the first packet — the
    persistent channel captures it all. Off by default: gates should assert
    programmed state, not live traffic."""

    command: str
    expect: TestExpectation
    parse: ParseMode | None = None
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class ValidationTest:
    """Run a case on each node; poll until it passes.

    `run` is ONE case for every node, or a DEVICE-KEYED dict (netlab device
    names: "vyos", "iol", "linux", ...) — the multi-vendor mechanism, so a
    single suite serves the VyOS and IOL flavors of a topology: each node
    picks its device's case, and a node whose device has none reports
    "skip", not an error. APPROVED (delta 17): keying is CASE-level (one
    atomic command/parse/expect recipe per device), not netlab's
    field-level parallel dicts — no key-consistency rules, one union in
    the types; the accepted cost is repeating a shared matcher across
    cases (a `default`-case merge is a possible ADDITIVE later extension).
    `wait` (0-600 s) polls until the expectation holds — the convergence
    knob."""

    nodes: list[str]
    run: TestCase | dict[str, TestCase]
    wait: int = 0
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestSuite:
    """Named test group. `stage` controls only *automatic* runs: config-time
    suites run after every configure and gate "config done". Any suite can be
    run manually."""

    tests: dict[str, ValidationTest]
    stage: Literal["config-time", "runtime"] = "runtime"
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestResult:
    """One (test, node) outcome. "fail" = expectation never held (after
    `wait`); "error" = command couldn't run, render, or parse; "skip" = the
    node's device has no case in a device-keyed test. `command` is the
    RENDERED command (what actually ran — the debugging artifact); `diff`
    is napalm-validate's structured complies/present/missing/extra report,
    populated only when a `compare` decided the outcome."""

    test: str
    node: str
    status: Literal["pass", "fail", "skip", "error"]
    command: str
    output: str
    detail: str
    diff: dict[str, object] | None
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class SuiteReport:
    suite: str
    stage: str
    passed: int
    failed: int
    skipped: int
    errored: int
    ran_at: datetime
    results: list[TestResult]


@dataclass(frozen=True, slots=True)
class TestSuitesResponse:
    """Declared suites + last run per suite (empty if never run) + the
    config-time gate from the most recent configure."""

    test_suites: dict[str, TestSuite]
    last_validation: dict[str, SuiteReport]
    config_time_status: ConfigTimeStatus  # APPROVED — wire today: config_time_ok


@dataclass(frozen=True, slots=True)
class LabFacts:
    """PROPOSED (delta 17, APPROVED, not served yet) the per-node fact
    namespace test-suite templates render against — netlab's node data
    from the expanded topology, keyed by SHORT node name.

    `nodes[n]` is exactly what `nodes.<n>` (and `node`, for the executing
    node) resolves to in a template. PROVISIONAL: the values are
    netlab-shaped raw dicts, deliberately unpinned until a stable subset
    is chosen (before v1.0) — this endpoint is the insulation layer, so
    consumers discover the namespace instead of assuming it."""

    nodes: dict[str, dict[str, object]]


# --------------------------------------------------------------------------- #
# Jobs (async lab operations — delta 12)
# --------------------------------------------------------------------------- #

JobKind = Literal["deploy", "configure", "destroy", "suite_run"]
JobStatus = Literal["running", "succeeded", "failed"]
# No "pending"/"queued" status: there is no queue — a job starts the moment
# its submit returns 202 (the one-running-job-per-lab mutex REJECTS a
# concurrent submit with 409 job_in_flight rather than queueing it).


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job FAILED — the error envelope, with TwinlabApiError's fields.
    `status_code` classifies the failure in HTTP vocabulary (422
    netlab_invalid, 502 upstream_error, ...) so error handling can match on
    the same codes everywhere; it is never an actual response status (job
    reads are 200)."""

    status_code: int
    code: str
    message: str
    extras: dict[str, object]


@dataclass(frozen=True, slots=True)
class Job:
    """One async lab operation, submitted by deploy/configure/destroy/suite
    run and read back via `get_job`/`list_jobs`.

    **failed = the operation could not run** (netlab rejected the stored
    definition, clab-api/runner unreachable, ...) with the envelope in
    `error`; an operation that RAN but produced a bad outcome — a config
    push failing on nodes, a red config-time gate — is a **succeeded** job
    whose `result.status` says so ("config_failed" / "validation_failed").

    `result` is populated only on "succeeded", typed by `kind` (APPROVED:
    the union, no per-kind accessors — the caller knows what it submitted):
      deploy -> DeployResponse        configure -> ConfigureResponse
      destroy -> DestroyResponse      suite_run -> SuiteReport

    `request` echoes the submitted parameters verbatim (APPROVED: a raw
    dict — history/display data, not a typed surface).

    A backend restart fails any then-running job (code "backend_restart" —
    the in-process task cannot survive; the record does). Finished jobs are
    pruned beyond the newest ~20 per lab."""

    id: UUID
    lab_name: str
    kind: JobKind
    status: JobStatus
    request: dict[str, object]
    result: DeployResponse | ConfigureResponse | DestroyResponse | SuiteReport | None
    error: JobError | None
    created_at: datetime
    finished_at: datetime | None  # None while running


@dataclass(frozen=True, slots=True)
class JobEvent:
    """PROPOSED (delta 16, APPROVED, not served yet) one job-lifecycle
    payload from `GET /events`, carried by the NAMED SSE event ``job``.

    A POKE, not a report: it says which job changed and to what, never the
    job's `result`/`error` — read those with `get_job` (they are typed by
    kind and would fork the shape if duplicated here).

    Emitted twice per job: at submit (status "running") and when it reaches a
    terminal state. `timestamp` is the job's `created_at` / `finished_at`
    respectively, so the event carries the same instant the record does.

    NOT a durable log: there is no replay on reconnect (see `events`)."""

    lab: str
    job_id: UUID
    kind: JobKind
    status: JobStatus
    timestamp: str


# --------------------------------------------------------------------------- #
# Custom-config shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class BuiltinTemplate:
    """Shipped read-only template: `config:` name, description, per-device
    files ({relpath: jinja source})."""

    name: str
    description: str
    files: dict[str, str]


@dataclass(frozen=True, slots=True)
class CustomConfigResponse:
    """Built-in library (identical for every lab) + this lab's user fileset.
    Relpaths match `^[A-Za-z0-9][A-Za-z0-9_./-]*\\.j2$`, max 128."""

    builtin: list[BuiltinTemplate]
    custom_config: dict[str, str]


# --------------------------------------------------------------------------- #
# Action vocabularies
# --------------------------------------------------------------------------- #

LabPowerAction = Literal["start", "stop", "restart", "pause", "unpause"]
NodePowerAction = Literal["start", "stop", "restart", "pause", "unpause"]
# QUIRK: lab pause/unpause fan out per node (clab-api has no lab pause);
# non-atomic — partial failure = 502 listing failed nodes; 409 if none running.


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #


class TerminalSession(AbstractAsyncContextManager["TerminalSession"]):
    """Node terminal: ``WS /api/v1/labs/{name}/nodes/{node}/terminal``
    (lab:terminal). Auth from the handshake cookie BEFORE accept; rejection
    closes 1008 with no reason. Upstream failure after accept closes 1011.

    Frames (clab-api's protocol, relayed verbatim):
      client -> {"type": "input"|"resize"|"close", ...}
      server -> {"type": "ready"} | {"type": "output", "data": <base64>}
              | {"type": "exit", ...}
    The client library owns the base64 decode and exposes bytes.

    QUIRK: path params are `name`/`node` vs `lab_name`/`node_name` elsewhere
    (OpenAPI-visible). PROPOSAL: rename during the rework.
    """

    async def send(self, data: bytes) -> None:
        raise NotImplementedError

    async def recv(self, timeout: float | None = None) -> bytes:
        """Decoded output. Raises on exit/close."""
        raise NotImplementedError

    async def resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


class TwinlabClient(AbstractAsyncContextManager["TwinlabClient"]):
    """Async Twinlab API client. One instance = one session (cookie jar on the
    instance); use as ``async with TwinlabClient(...) as client``. Non-2xx
    raises ``TwinlabApiError``.

    The four long operations (deploy/configure/destroy/suite run) are ASYNC
    JOBS (delta 12): submit returns 202 + a running `Job`; the caller polls
    `get_job` (or `wait_job`) for the terminal state. Every HTTP call is
    short — `action_timeout` is the default `wait_job` deadline, i.e. how
    long a submitted operation may take end to end.
    """

    def __init__(
        self,
        base_url: str,
        *,
        subpath: str = "/api/v1",
        api_key: str | None = None,
        timeout: float = 30.0,
        action_timeout: float = 1800.0,
        verify_tls: bool = True,
    ) -> None:
        """`base_url` = backend origin (e.g. "http://localhost:8000");
        `subpath` is appended to it. `api_key` authenticates every request as
        `Authorization: Bearer <key>` instead of a login session (PROPOSED —
        no backend support yet; `login` still works on a keyed client but is
        pointless). `action_timeout` is the default `wait_job` deadline —
        submits themselves are fast 202s (delta 12)."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Close the underlying HTTP client (also done by `async with`)."""
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Health (unauthenticated)
    # ------------------------------------------------------------------ #

    async def health(self) -> Liveness:
        """GET /health — dependency-free liveness."""
        raise NotImplementedError

    async def ready(self) -> Readiness:
        """GET /health/ready — parses both 200 and 503 (degraded is data, not
        an error). Gate the black-box suite on this."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    async def login(self, username: str, password: str) -> UserInfo:
        """POST /auth/login — sets the session cookie. 401 "invalid
        credentials" for both unknown-user and wrong-password (deliberately
        opaque)."""
        raise NotImplementedError

    async def logout(self) -> None:
        """POST /auth/logout — 204; idempotent."""
        raise NotImplementedError

    async def me(self) -> UserInfo:
        """GET /auth/me — identity + GLOBAL roles/permissions."""
        raise NotImplementedError

    async def change_password(self, current: str, new: str) -> None:
        """PROPOSED (APPROVED, not served yet) PUT /auth/password —
        self-service change, requires the current password. 204; revokes the
        user's OTHER sessions, keeps this one."""
        raise NotImplementedError

    # API keys — PROPOSED (no backend support yet): self-service long-lived
    # credentials for automation (CI, the black-box suite), sent as
    # `Authorization: Bearer <key>`. A key acts as its creating user with that
    # user's permissions (no separate key scoping in v1); stored hashed;
    # deleting/deactivating the user kills its keys.

    async def create_api_key(self, name: str) -> ApiKeyCreated:
        """PROPOSED POST /auth/api-keys — 201. The secret is returned only
        here. 409 name_taken (per user)."""
        raise NotImplementedError

    async def list_api_keys(self) -> list[ApiKey]:
        """PROPOSED GET /auth/api-keys — the caller's own keys, no secrets."""
        raise NotImplementedError

    async def revoke_api_key(self, key_id: UUID) -> None:
        """PROPOSED DELETE /auth/api-keys/{key_id} — 204, immediate."""
        raise NotImplementedError

    # SSH keys (delta 13): registered PUBLIC keys unlock the stack's SSH jump
    # host. Through it a key's owner reaches ALL TCP ports of nodes in labs
    # where they hold lab:terminal (owner-implicit included) — TCP forwarding
    # only, no shell/PTY on the jump itself. Authorization is re-evaluated
    # from live RBAC at every NEW connection: deleting a key, revoking
    # lab:terminal, or deactivating the user takes effect on the next
    # connection (established tunnels survive until closed), and the
    # permitted node set is frozen per connection (reconnect after a
    # redeploy changes node IPs).

    async def create_ssh_key(self, name: str, public_key: str) -> SshKey:
        """POST /auth/ssh-keys — 201. `public_key` is one OpenSSH
        authorized_keys-format line ("<algorithm> <base64> [comment]", no
        options). 422 invalid_public_key / unsupported_key_type; 409
        name_taken (per user); 409 key_already_registered — fingerprints are
        GLOBALLY unique, a key identifies one person at the jump."""
        raise NotImplementedError

    async def generate_ssh_key(self, name: str) -> SshKeyGenerated:
        """POST /auth/ssh-keys/generate — 201. Server-side ed25519 pair for
        users without their own key: the public half is registered under
        `name` (equivalent to create_ssh_key from then on), the private half
        is returned only here and never stored. 409 name_taken (per user);
        a fingerprint conflict cannot occur (the key is freshly random)."""
        raise NotImplementedError

    async def list_ssh_keys(self) -> list[SshKey]:
        """GET /auth/ssh-keys — the caller's own keys."""
        raise NotImplementedError

    async def delete_ssh_key(self, key_id: UUID) -> None:
        """DELETE /auth/ssh-keys/{key_id} — 204. 404 ssh_key_not_found (own
        keys only; someone else's id is indistinguishable from absent)."""
        raise NotImplementedError

    async def get_ssh_access(self) -> SshAccess:
        """GET /ssh-access — jump-host coordinates; any authenticated user."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Users (global user:manage)
    # ------------------------------------------------------------------ #
    # PROPOSED endpoints below (approved) are marked in their docstrings.

    async def create_user(
        self, username: str, password: str, roles: set[str] | None = None
    ) -> UserSummary:
        """POST /users — 201. `roles` = GLOBAL roles; omitted/empty = the
        baseline "user" role (authenticated, no access). 409 username_taken;
        422 unknown_roles; password min 8."""
        raise NotImplementedError

    async def list_users(self) -> list[UserSummary]:
        """GET /users. No pagination anywhere (explicit v1.0 decision)."""
        raise NotImplementedError

    async def get_user(self, user_id: UUID) -> UserSummary:
        """PROPOSED (APPROVED, not served yet) GET /users/{user_id} — 404
        user_not_found."""
        raise NotImplementedError

    async def set_user_roles(self, user_id: UUID, roles: set[str]) -> UserSummary:
        """PUT /users/{user_id}/roles — full replace of global roles.
        404 user_not_found; 422 unknown/non-global role."""
        raise NotImplementedError

    async def set_user_password(self, user_id: UUID, password: str) -> None:
        """PROPOSED (APPROVED, not served yet) PUT /users/{user_id}/password —
        admin reset. 204; revokes ALL the user's sessions."""
        raise NotImplementedError

    async def set_user_active(self, user_id: UUID, is_active: bool) -> UserSummary:
        """PROPOSED (APPROVED, not served yet) PUT /users/{user_id}/active —
        deactivate/reactivate. Deactivation revokes the user's sessions and
        stops their API keys; record, bindings, and owned labs are untouched —
        the reversible soft alternative to delete_user. Refuses deactivating
        the last active admin (409, same rule as delete)."""
        raise NotImplementedError

    async def delete_user(self, user_id: UUID) -> None:
        """PROPOSED (APPROVED, not served yet) DELETE /users/{user_id} — 204.

        Semantics to pin: revoke the user's sessions; delete role bindings
        they RECEIVED (cascade); keep rows where they were the actor — owned
        labs -> owner NULL (FK is already SET NULL), grants they MADE keep
        granted_by NULL. Refusing to delete the last admin (409) — APPROVED."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Groups (global group:manage)
    # ------------------------------------------------------------------ #

    async def create_group(self, name: str, description: str = "") -> GroupSummary:
        """POST /groups — 201. 409 name_taken."""
        raise NotImplementedError

    async def list_groups(self) -> list[GroupSummary]:
        """GET /groups."""
        raise NotImplementedError

    async def get_group(self, group_id: UUID) -> GroupSummary:
        """PROPOSED (APPROVED, not served yet) GET /groups/{group_id} — 404
        group_not_found."""
        raise NotImplementedError

    async def delete_group(self, group_id: UUID) -> None:
        """DELETE /groups/{group_id} — 204. Also deletes the group's bindings;
        members untouched."""
        raise NotImplementedError

    async def set_group_members(
        self, group_id: UUID, user_ids: list[UUID]
    ) -> GroupSummary:
        """PUT /groups/{group_id}/members — full replace. 404 group_not_found;
        422 user_not_found."""
        raise NotImplementedError

    async def set_group_roles(self, group_id: UUID, roles: set[str]) -> GroupSummary:
        """PUT /groups/{group_id}/roles — full replace of GLOBAL roles (lab
        grants go through create_grant). 422 non-global-bindable role."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Catalog / directory (any authenticated user)
    # ------------------------------------------------------------------ #

    async def list_roles(self) -> list[Role]:
        """GET /roles — the code-defined role catalog."""
        raise NotImplementedError

    async def list_principals(self) -> Principals:
        """GET /principals. QUIRK (recorded in ROADMAP): exposes all
        user/group names to any authenticated user — accepted for now; revisit
        if enumeration becomes a concern."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — lifecycle
    # ------------------------------------------------------------------ #

    # Lifecycle split (APPROVED, applied — wire today: one-shot POST /labs
    # carrying name+definition+suites+templates, and a separate /redeploy):
    # create (record only) -> author (the PUTs) -> deploy (from the stored
    # record). The mgmt-subnet reservation moves to the cheap create call,
    # killing the reserve/retry race machinery around the slow deploy.

    async def create_lab(self, name: str) -> LabDetail:
        """POST /labs {name} — 201. GLOBAL lab:create; caller becomes owner.

        Record only: allocates the lab's mgmt /24, status "created" — no
        definition yet, nothing deployed. `name` is the lab's durable identity.
        409 name taken; 503 subnet pool exhausted."""
        raise NotImplementedError

    async def list_labs(self) -> list[LabSummary]:
        """GET /labs — filtered to labs with lab:read (owned, granted, group,
        global). No access = [] — never 403."""
        raise NotImplementedError

    async def get_lab(self, name: str) -> LabDetail:
        """GET /labs/{name} — lab:read. 404 if absent OR unreadable; 502 on
        clab-api failure other than lab-not-deployed."""
        raise NotImplementedError

    async def update_definition(self, name: str, definition: str) -> LabDetail:
        """PUT /labs/{name} — lab:edit. Replaces the STORED definition only
        (applies on next deploy). The definition must name each node's `device`
        and the `provider`; any `name:` in it is overridden by the record, and
        the mgmt subnet is re-pinned (explicit `addressing.mgmt.ipv4` wins).
        Validated by a dry `netlab create` (422). 409 subnet clash."""
        raise NotImplementedError

    async def deploy_lab(
        self,
        name: str,
        *,
        configure: bool = False,
        skip_config_time_checks: bool = False,
    ) -> Job:
        """POST /labs/{name}/deploy — lab:edit. **202 + the running deploy
        Job** (delta 12 — wire today: a synchronous long call returning
        DeployResponse directly). Deploys from the stored definition + suites
        + custom config: fresh if "created"/"destroyed", overwrite-in-place
        if running. The terminal job's `result` is a DeployResponse.

        Pre-accept (synchronous) errors: 409 no stored definition yet; 409
        `job_in_flight` — ONE running job per lab, any kind. Post-accept
        failures — netlab rejecting the stored definition, clab-api/runner
        unreachable — fail the JOB (`error` carries the envelope); a push
        that ran but failed and a red gate stay job successes
        ("config_failed" / "validation_failed" result statuses)."""
        raise NotImplementedError

    # (create_and_deploy convenience removed per review: a client-side
    # composition cannot be atomic — a partway failure would strand a
    # "created" record — and the bar was "remove unless atomic". Callers
    # compose create_lab + PUTs + deploy_lab explicitly.)

    async def configure_lab(
        self, name: str, *, skip_config_time_checks: bool = False
    ) -> Job:
        """POST /labs/{name}/configure — lab:configure. **202 + the running
        configure Job** (result: ConfigureResponse). Pushes config from the
        stored definition, then runs config-time suites unless skipped (the
        automatic run rides lab:configure, not lab:validate — deliberate).
        Pre-accept: 409 no definition; 409 job_in_flight. A push that
        couldn't run fails the job; one that ran-but-failed succeeds with
        result.status="config_failed"."""
        raise NotImplementedError

    async def destroy_lab(self, name: str, *, remove: bool = False) -> Job:
        """DELETE /labs/{name} — lab:destroy. **202 + the running destroy
        Job** (result: DestroyResponse).

        remove=False: tear down; record -> "destroyed" (redeployable, KEEPS
        its mgmt-subnet reservation so a redeploy reproduces the same
        environment). Requires the lab to be RUNNING — a synchronous 409 at
        submit, via a fast live-state pre-check.
        remove=True: also soft-delete the record and RELEASE its mgmt-subnet
        reservation; teardown best-effort, so a down lab is fine. The job
        stays pollable AFTER the soft-delete — job reads see soft-deleted
        labs, so the terminal state is always reachable.
        Pre-accept: 409 lab_not_running (remove=False); 409 job_in_flight."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — jobs (async operations, delta 12)
    # ------------------------------------------------------------------ #

    async def get_job(self, lab_name: str, job_id: UUID) -> Job:
        """GET /labs/{lab_name}/jobs/{job_id} — lab:read. 404 hides both an
        unreadable lab and an unknown job id. Works on a soft-deleted lab
        (a destroy-with-remove job must stay pollable to its terminal
        state)."""
        raise NotImplementedError

    async def list_jobs(self, lab_name: str, *, limit: int = 20) -> list[Job]:
        """GET /labs/{lab_name}/jobs?limit= — lab:read, newest first. Recent
        history, not an audit log: finished jobs beyond the newest ~20 per
        lab are pruned (and a re-created lab name starts with an empty
        history — jobs don't leak across incarnations)."""
        raise NotImplementedError

    async def list_all_jobs(self, *, limit: int = 20) -> list[Job]:
        """PROPOSED (delta 15, APPROVED, not served yet) GET /jobs?limit= —
        recent jobs across every lab the caller may read, newest first (each
        `Job` names its `lab_name`). Any authenticated user; the per-lab
        filter is the same readable set `events` uses, so this never leaks a
        lab's existence. `limit` is 1-200 (422 outside).

        Jobs of REMOVED labs are excluded: a destroy-with-remove job drops
        out of this list when its lab record does, and its terminal state is
        read with `get_job`, which stays readable on a removed lab."""
        raise NotImplementedError

    async def wait_job(
        self,
        lab_name: str,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_interval: float = 2.0,
    ) -> Job:
        """Poll `get_job` until the job is terminal; return the terminal Job.
        Pure client-side convenience — no wire surface beyond the polling.

        Does NOT raise on a failed job — the caller inspects
        status/result/error (APPROVED: no raise-on-failure flag). Raises
        stdlib TimeoutError (APPROVED) when `timeout` (default: the
        client's `action_timeout`) elapses with the job still running —
        the job keeps running server-side; the caller can resume waiting.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — test suites
    # ------------------------------------------------------------------ #

    async def get_test_suites(self, name: str) -> TestSuitesResponse:
        """GET /labs/{name}/test-suites — lab:read."""
        raise NotImplementedError

    async def facts(self, name: str) -> LabFacts:
        """PROPOSED (delta 17, APPROVED, not served yet) GET
        /labs/{name}/facts — lab:read. The per-node fact namespace suite
        templates render against (see LabFacts: PROVISIONAL raw netlab
        node data until pinned, pre-v1.0). 409 ``no_definition`` on a bare
        created record — no definition, no facts. Derived from the same
        dry `netlab create` that validates a PUT and persisted like the
        link table, so reads never pay the subprocess cost."""
        raise NotImplementedError

    async def put_test_suites(
        self, name: str, suites: dict[str, TestSuite]
    ) -> TestSuitesResponse:
        """PUT /labs/{name}/test-suites — lab:edit. Full replace; takes effect
        on the next run.

        PROPOSAL (delta 17, APPROVED): schema violations (two matchers,
        compare without parse, bad regex) stay 422 as today; Jinja templates
        are syntax-checked always and dry-rendered against the lab's node
        facts when a definition exists — either failure is 422
        ``template_invalid`` naming the suite/test/field."""
        raise NotImplementedError

    async def run_test_suite(self, name: str, suite: str) -> Job:
        """POST /labs/{name}/test-suites/{suite}/run — lab:validate. **202 +
        the running suite_run Job** (result: SuiteReport — its worst case is
        the sum of every test's `wait`, hence a job). Runs one suite (any
        stage); persists as its last run but NEVER moves the config-time
        gate. Pre-accept: 404 unknown suite; 409 job_in_flight."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — custom config
    # ------------------------------------------------------------------ #

    async def get_custom_config(self, name: str) -> CustomConfigResponse:
        """GET /labs/{name}/custom-config — lab:read."""
        raise NotImplementedError

    async def put_custom_config(
        self, name: str, fileset: dict[str, str]
    ) -> CustomConfigResponse:
        """PUT /labs/{name}/custom-config — lab:edit. Full replace of the USER
        fileset. 409 if a path shadows a built-in. Applies on the next
        configure/deploy."""
        raise NotImplementedError

    # stopped here

    # ------------------------------------------------------------------ #
    # Labs — runtime control & observability (live clab-api state)
    # ------------------------------------------------------------------ #

    async def lab_power(self, name: str, action: LabPowerAction) -> LabActionResponse:
        """POST /labs/{name}/{action} — lab:configure. pause/unpause fan out
        per node (see LabPowerAction QUIRK)."""
        raise NotImplementedError

    async def node_power(
        self, name: str, node: str, action: NodePowerAction
    ) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/{action} — lab:configure."""
        raise NotImplementedError

    async def save_config(self, name: str) -> SaveConfigResponse:
        """POST /labs/{name}/save — lab:configure. containerlab save."""
        raise NotImplementedError

    async def node_logs(
        self, name: str, node: str, *, tail: int = 200
    ) -> NodeLogsResponse:
        """GET /labs/{name}/nodes/{node}/logs?tail= — lab:read. Container
        logs, not NOS syslog."""
        raise NotImplementedError

    async def interfaces(
        self, name: str, *, node: str | None = None
    ) -> list[NodeInterfaces]:
        """GET /labs/{name}/interfaces[?node=] — lab:read. See NodeInterfaces
        QUIRK (container-name keys)."""
        raise NotImplementedError

    async def links(self, name: str) -> LabLinks:
        """PROPOSED (delta 14 APPROVED, not served yet) GET /labs/{name}/links — the lab's
        logical link table with derived oper state. lab:read (404
        existence-hiding). 409 ``no_definition`` on a bare created record —
        an empty table would be indistinguishable from a definition with no
        links. Works on ANY authored lab: undeployed labs return the full
        table with every ``oper_state`` "unknown" and ``live=False``. The
        live merge is best-effort: an interface-inventory failure degrades to
        unknown states, never a 5xx."""
        raise NotImplementedError

    async def show_netem(self, name: str, node: str) -> list[NetemImpairment]:
        """GET /labs/{name}/nodes/{node}/netem — lab:read. Lists only the
        interfaces with ACTIVE impairment (implementation finding: tc/clab
        omit unshaped interfaces) — a cleared interface is absent, not
        zeroed."""
        raise NotImplementedError

    async def set_netem(
        self,
        name: str,
        node: str,
        interface: str,
        *,
        delay: Duration | None = None,
        jitter: Duration | None = None,
        loss: float | None = None,
        rate: int | None = None,
        corruption: float | None = None,
    ) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/netem — lab:configure. REPLACE
        semantics (APPROVED): the call states the interface's COMPLETE desired
        impairment — an omitted/None dimension is cleared, and a call with no
        impairments clears everything (subsuming the removed /netem/reset
        endpoint). jitter requires delay; loss/corruption 0-100 %, rate kbit/s.

        Wire today: "50ms"-style duration strings, omitted = unchanged, an
        at-least-one-impairment rule, and a separate POST .../netem/reset."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — grants & ownership (lab:grant on the lab)
    # ------------------------------------------------------------------ #

    async def list_grants(self, name: str) -> list[Grant]:
        """GET /labs/{name}/grants."""
        raise NotImplementedError

    async def create_grant(
        self,
        name: str,
        principal_type: Literal["user", "group"],
        principal_id: UUID,
        role: str,
    ) -> Grant:
        """POST /labs/{name}/grants — 201. 422 unless the role is lab-bindable;
        403 anti-escalation (role's permissions must be ⊆ the caller's on this
        lab). Duplicates are idempotent."""
        raise NotImplementedError

    async def delete_grant(self, name: str, binding_id: UUID) -> None:
        """DELETE /labs/{name}/grants/{binding_id} — 204. 404 if absent or on
        another lab."""
        raise NotImplementedError

    async def transfer_owner(self, name: str, user_id: UUID) -> LabOwner:
        """PUT /labs/{name}/owner. Requires owner-EQUIVALENCE (the full owner
        permission set on the lab), else 403. 404 unknown user.

        Returns `LabOwner` (APPROVED — wire today: a fake grant shape with the
        lab's UUID as `id` and the non-catalog role "owner")."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Streams
    # ------------------------------------------------------------------ #

    # AsyncGenerator, not AsyncIterator (implementation finding): callers that
    # abandon the stream early need a deterministic close (aclose /
    # contextlib.aclosing) so the underlying connection is released.
    def events(self) -> AsyncGenerator[LabEvent | JobEvent, None]:
        """GET /events (SSE) — any authenticated user; filtered to readable
        labs (set refreshes ~30 s, so a mid-stream grant lags up to that).
        Iterate with `async for`; keepalives are consumed, not yielded.

        PROPOSED (delta 16, APPROVED) two payloads, discriminated by the SSE
        event NAME and yielded as a union (match with `isinstance`):

          ``lab`` -> LabEvent   container lifecycle, relayed from
                                containerlab. A configure or suite-run job
                                touches no container, so it emits none.
          ``job`` -> JobEvent   a job was submitted or reached a terminal
                                state — the signal that replaces polling.

        NOT a durable log: the stream has no replay (no Last-Event-ID), so a
        reconnect silently misses whatever happened while it was down. A
        consumer that must not miss a completion still reads the record —
        `wait_job` polls for exactly this reason.

        (wire today: one unnamed event carrying the LabEvent payload;
        completion is discovered by polling only.)"""
        raise NotImplementedError

    def terminal(
        self,
        name: str,
        node: str,
        *,
        protocol: Literal["ssh", "shell"] = "ssh",
        cols: int = 80,
        rows: int = 24,
        ssh_username: str | None = None,
    ) -> AbstractAsyncContextManager[TerminalSession]:
        """Open the node terminal WS (lab:terminal; see TerminalSession) —
        `async with client.terminal(...) as term`. `ssh_username`: clab-api
        defaults to "admin" (wrong for e.g. VyOS); ignored for
        protocol="shell"."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Appendix — shipped catalogs (APPROVED: pinned as versioned contract facts)
# --------------------------------------------------------------------------- #
# The role catalog and builtin-template library are code-defined in the
# backend; third-party clients must still QUERY them (GET /roles, GET
# /labs/{name}/custom-config) rather than hardcode. They are enumerated here
# so a catalog change is, by definition, a contract change (and a black-box
# suite change) — not a silent drift.
#
# Permissions — lab-scoped (bindable per-lab or globally):
#   lab:read, lab:edit, lab:configure, lab:validate, lab:terminal,
#   lab:destroy, lab:grant
# Permissions — global-only:
#   lab:create, user:manage, group:manage
#
# Role catalog (scope — permissions):
#   admin           global — every permission
#   global_operator global — lab:create + all seven lab-scoped
#   global_viewer   global — lab:read
#   creator         global — lab:create
#   user            global — none (the baseline role every new user gets)
#   lab_owner       lab    — all seven lab-scoped (also the owner-implicit set)
#   lab_manager     lab    — all lab-scoped EXCEPT lab:destroy
#   lab_operator    lab    — lab:read, lab:configure, lab:validate, lab:terminal
#   lab_viewer      lab    — lab:read
#
# Shipped builtin custom-config templates: mpls_te, ip_sla.
