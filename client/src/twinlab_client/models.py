"""Wire models for the Twinlab API v1.0.

Frozen dataclasses mirroring the settled contract (`docs/twinlab_client_shape.py`
in the Twinlab repository). These shapes carry no behavior; parsing to and from
the wire lives in `_wire.py`.

Unordered unique collections (roles, permissions, scopes) are `set`s here; the
wire is a JSON array either way. Ids are UUIDs.
"""

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

# --------------------------------------------------------------------------- #
# Vocabularies
# --------------------------------------------------------------------------- #
# Each Literal alias has a runtime tuple alongside it (same values) so parsers
# can validate without repeating the vocabulary.

LabStatus = Literal["created", "deploying", "deployed", "destroyed"]
LAB_STATUSES: Final[tuple[LabStatus, ...]] = ("created", "deploying", "deployed", "destroyed")

DeployStatus = Literal["deployed", "configured", "config_failed", "validation_failed"]
DEPLOY_STATUSES: Final[tuple[DeployStatus, ...]] = (
    "deployed",
    "configured",
    "config_failed",
    "validation_failed",
)

ConfigureStatus = Literal["configured", "config_failed", "validation_failed"]
CONFIGURE_STATUSES: Final[tuple[ConfigureStatus, ...]] = (
    "configured",
    "config_failed",
    "validation_failed",
)

# No "skipped" state on purpose: a skipped gate RETAINS the previous result;
# "no config-time suites" = "not_run".
ConfigTimeStatus = Literal["not_run", "passed", "failed"]
CONFIG_TIME_STATUSES: Final[tuple[ConfigTimeStatus, ...]] = ("not_run", "passed", "failed")

# Docker engine's container-state vocabulary; the backend normalizes clab-api's
# passthrough to it.
ContainerState = Literal["created", "running", "paused", "restarting", "removing", "exited", "dead"]
CONTAINER_STATES: Final[tuple[ContainerState, ...]] = (
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
)

NodeConfigStatus = Literal["configured", "failed"]
NODE_CONFIG_STATUSES: Final[tuple[NodeConfigStatus, ...]] = ("configured", "failed")

# The derived per-link oper state (delta 14) — pinned because Twinlab computes
# it. Two stages (wording amended 2026-08-05): each endpoint classifies up /
# down / unknown, where DOWN IS A CLOSED SET (down, lowerlayerdown, notpresent)
# and anything else — an unresolved endpoint, an unrecognized value, or a
# carrier-less interface reporting the string "unknown" — is unknown, never
# assumed down. Then: any unknown endpoint -> "unknown"; all up -> "up"; all
# down -> "down"; a mix -> "degraded".
LinkOperState = Literal["up", "degraded", "down", "unknown"]
LINK_OPER_STATES: Final[tuple[LinkOperState, ...]] = ("up", "degraded", "down", "unknown")

DestroyStatus = Literal["destroyed", "deleted"]
DESTROY_STATUSES: Final[tuple[DestroyStatus, ...]] = ("destroyed", "deleted")

JobKind = Literal["deploy", "configure", "destroy", "suite_run"]
JOB_KINDS: Final[tuple[JobKind, ...]] = ("deploy", "configure", "destroy", "suite_run")

# No "pending"/"queued": there is no queue — a job starts the moment its
# submit returns 202 (a concurrent submit is rejected 409, not queued).
JobStatus = Literal["running", "succeeded", "failed"]
JOB_STATUSES: Final[tuple[JobStatus, ...]] = ("running", "succeeded", "failed")

# How a STEP reads, not how the job ended: a warning step (an image that has to
# be pulled) or an error step (the config push failed on 2 of 7 nodes) can both
# sit inside a succeeded job.
JobStepLevel = Literal["info", "warning", "error"]
JOB_STEP_LEVELS: Final[tuple[JobStepLevel, ...]] = ("info", "warning", "error")

ReadinessStatus = Literal["ready", "degraded"]
READINESS_STATUSES: Final[tuple[ReadinessStatus, ...]] = ("ready", "degraded")

RoleScope = Literal["global", "lab"]
ROLE_SCOPES: Final[tuple[RoleScope, ...]] = ("global", "lab")

PrincipalType = Literal["user", "group"]
PRINCIPAL_TYPES: Final[tuple[PrincipalType, ...]] = ("user", "group")

SuiteStage = Literal["config-time", "runtime"]
SUITE_STAGES: Final[tuple[SuiteStage, ...]] = ("config-time", "runtime")

TestStatus = Literal["pass", "fail", "skip", "error"]
TEST_STATUSES: Final[tuple[TestStatus, ...]] = ("pass", "fail", "skip", "error")

DurationUnit = Literal["us", "ms", "s"]
DURATION_UNITS: Final[tuple[DurationUnit, ...]] = ("us", "ms", "s")

# Lab-level pause/unpause fan out per node (clab-api has no lab pause); the fan
# out is non-atomic — partial failure is a 502 listing the failed nodes.
LabPowerAction = Literal["start", "stop", "restart", "pause", "unpause"]
NodePowerAction = Literal["start", "stop", "restart", "pause", "unpause"]

TerminalProtocol = Literal["ssh", "shell"]


# --------------------------------------------------------------------------- #
# Auth / identity shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UserInfo:
    """`GET /auth/me` / login response. GLOBAL roles/permissions only —
    per-lab permissions ride on each lab payload."""

    username: str
    email: str
    display_name: str
    roles: set[str]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class LinkedIdentity:
    """One OIDC provider identity linked to a user (delta 33). The link, not the
    email, is what a later provider sign-in resolves through."""

    id: UUID
    provider: str  # the provider's name
    subject: str  # the provider's `sub` claim, opaque
    email_at_link: str  # the claim's email when the link was made (audit only)
    created_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class UserSummary:
    """One user (`/users`). `roles` = global roles. `username` is the
    password-login and RBAC principal name; `display_name` is what a UI shows.
    `email` is unique case-insensitively."""

    id: UUID
    username: str
    email: str
    display_name: str
    is_active: bool
    roles: set[str]
    identities: list[LinkedIdentity]


@dataclass(frozen=True, slots=True)
class UserCreated:
    """`POST /users` response. `generated_password` is set only when the request
    omitted the password — the only time the server-generated password is
    returned."""

    user: UserSummary
    generated_password: str | None


@dataclass(frozen=True, slots=True)
class LoginProvider:
    """One entry of the (unauthenticated) login page's provider list."""

    name: str
    display_name: str
    icon: str | None  # a data: URI, or None (render a monogram)


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
    scopes: set[RoleScope]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class ApiKey:
    """One API key, as listings show it — never the secret."""

    id: UUID
    name: str  # caller-chosen label, e.g. "ci"
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApiKeyCreated:
    """Create response — the only time the secret is returned."""

    key: str  # the bearer secret; shown once, stored hashed server-side
    info: ApiKey


@dataclass(frozen=True, slots=True)
class SshKey:
    """One registered SSH public key (`/auth/ssh-keys`).

    Registering a key unlocks the stack's SSH jump host for its owner (see
    `TwinlabClient.create_ssh_key` for the connection semantics). Nothing
    here is secret — the user keeps the private key — so create returns this
    same shape."""

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
    """`GET /ssh-access` — the jump-host coordinates.

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


OidcIconType = Literal["image/svg+xml", "image/png", "image/webp"]


@dataclass(frozen=True, slots=True)
class OidcProvider:
    """An admin-configured OIDC provider (`/oidc-providers`, user:manage).

    `name` and `issuer` are immutable. The client secret is WRITE-ONLY: a read
    says only whether one is set (`has_client_secret`) and whether it still
    decrypts under the deployment's key (`client_secret_readable`)."""

    name: str
    display_name: str
    issuer: str
    client_id: str
    has_client_secret: bool
    client_secret_readable: bool
    scopes: list[str]
    allow_create_users: bool
    allow_email_tying: bool
    trust_email: bool  # an ABSENT email_verified counts as verified
    # Lowercase; a verified email must be at one of them to tie or create
    # (an exact match: list each subdomain). Empty = any domain. Never applied
    # to an identity that is already linked.
    allowed_email_domains: list[str]
    default_group: Principal | None  # joined at account creation only
    enabled: bool
    icon: str | None  # a data: URI
    # The redirect URI to register at the provider; None while the deployment's
    # PUBLIC_ORIGIN is unset (provider sign-in is then off).
    callback_url: str | None
    linked_users: int
    created_at: datetime
    updated_at: datetime


class Unchanged(enum.Enum):
    """The "leave it as stored" value of a write-only field on a replace (the
    client secret) — None cannot say it, since None means remove."""

    UNCHANGED = "unchanged"


UNCHANGED = Unchanged.UNCHANGED


@dataclass(frozen=True, slots=True)
class LabOwner:
    """`PUT /labs/{name}/owner` response."""

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
    no longer exists (defensive — only reachable via out-of-band DB edits)."""

    id: UUID
    principal_type: PrincipalType
    principal_id: UUID
    principal_name: str | None
    role: str


# Pinned because Twinlab derives it (delta 18): netlab's own vocabulary for
# linux devices is `role: host`; everything configurable is a router here.
DeviceRole = Literal["router", "host"]
DEVICE_ROLES: Final[tuple[DeviceRole, ...]] = ("router", "host")


@dataclass(frozen=True, slots=True)
class CatalogDevice:
    """One deployable device this deployment supports (delta 18).

    The set is server-curated policy — the tested platforms plus the linux
    host device. A definition naming an uncataloged device is not rejected;
    it is simply unpromised."""

    device: str  # netlab device slug ("vyos", "frr", "linux") — what a
    #              definition's `device:` takes; the set widens as platforms
    #              get tested, so it is not pinned.
    label: str  # display name, e.g. "FRRouting"
    role: DeviceRole
    modules: list[str]  # netlab config modules the device can run (netlab's
    #                     vocabulary; consumers intersect with what they author)
    image: str  # netlab's default clab image (untagged means ":latest")
    image_present: bool | None  # default image exists on the host Docker
    #                             daemon — best-effort; None = could not check
    #                             (see DeviceCatalog.live)
    config_import: bool  # delta 22: dumped running configs of this device can
    #                      be imported (POST /import/*). Narrower than
    #                      deployability — linux has no config-dump concept.
    # Delta 31: the two per-device capabilities a test CASE depends on. Both
    # are derived server-side from the tables that decide, so they cannot
    # drift from behaviour — and the two axes are independent: linux has no
    # CLI but does have a TextFSM template set, FRR has a CLI but speaks JSON.
    cli_mode: bool  # `TestCase.mode = "cli"` reaches a CLI here. False means
    #                 the device's shell IS its interface, so a cli case 422s.
    textfsm: bool  # `TestCase.parse = "textfsm"` resolves a platform here.
    #                False means such a case errors — Twinlab never silently
    #                falls back to raw output.


@dataclass(frozen=True, slots=True)
class DeviceCatalog:
    """`GET /catalog` — what this deployment can actually run (delta 18)."""

    devices: list[CatalogDevice]
    live: bool  # False = image presence could not be resolved; every
    #             image_present is then None


# --------------------------------------------------------------------------- #
# Host resources (delta 30)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class HostCpu:
    cores: int
    utilization_percent: float  # host-wide, over the server's sample window
    load1: float
    load5: float
    load15: float


@dataclass(frozen=True, slots=True)
class HostMemory:
    total_bytes: int
    used_bytes: int
    available_bytes: int  # what a new lab could claim — NOT total minus used,
    #                       which counts reclaimable page cache as spent
    percent: float


@dataclass(frozen=True, slots=True)
class HostSwap:
    total_bytes: int
    used_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostDisk:
    path: str  # the path asked about; figures are for its filesystem
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostResources:
    """`GET /host` — what the machine running the labs is spending (delta 30).

    Sampled by the server on a timer, so `sampled_at` is the reading's real
    age: a timestamp older than a few seconds means sampling is failing, not
    that the values were just refreshed."""

    sampled_at: datetime
    cpu: HostCpu
    memory: HostMemory
    swap: HostSwap
    disks: list[HostDisk]  # only filesystems the backend can see


@dataclass(frozen=True, slots=True)
class DockerDiskUsage:
    """One row of the daemon's disk footprint, mirroring `docker system df`."""

    kind: str  # "images" | "containers" | "volumes" | "build_cache" — the
    #            vocabulary may grow with the daemon, so it is not pinned
    total: int
    active: int
    size_bytes: int
    reclaimable_bytes: int  # what a prune could return; an unused image counts
    #                         only its UNSHARED layers


@dataclass(frozen=True, slots=True)
class DockerUsage:
    """`GET /host/docker` — the Docker daemon's counts and disk footprint
    (delta 30). Read through the netlab-runner, the only component holding the
    Docker socket, so a runner outage is a 503 rather than zeros."""

    root_dir: str  # the daemon's data root; its filesystem is NOT necessarily
    #                one of HostResources.disks
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: list[DockerDiskUsage]


@dataclass(frozen=True, slots=True)
class NodeUsage:
    """One node's live cost (delta 30).

    Every measure is nullable and a node that is not running carries none of
    them: a stopped container has nothing to report, and 0% would claim an
    idle node where there is no running one. `state` says which case this is."""

    node: str
    container: str
    state: str
    cpu_percent: float | None  # a share of the WHOLE host, so a node pinning
    #                            two cores reads 200%
    memory_bytes: int | None
    memory_limit_bytes: int | None
    net_rx_bytes: int | None
    net_tx_bytes: int | None
    pids: int | None


@dataclass(frozen=True, slots=True)
class LabUsage:
    """`GET /labs/{name}/usage` — what a lab's nodes cost right now."""

    lab: str
    sampled_at: datetime
    nodes: list[NodeUsage]
    live: bool  # False = the measures could not be collected (undeployed lab,
    #             or clab-api / the runner unreachable). Never an error: an
    #             undeployed lab legitimately costs nothing.


# --------------------------------------------------------------------------- #
# Template library shapes (delta 21)
# --------------------------------------------------------------------------- #


# Two sibling collections with independent namespaces: /templates/network
# (complete definitions) and /templates/node (single-node fragments).
TemplateTier = Literal["builtin", "user"]
TEMPLATE_TIERS: Final[tuple[TemplateTier, ...]] = ("builtin", "user")


@dataclass(frozen=True, slots=True)
class NetworkTemplateSummary:
    """One network-collection entry, content omitted (delta 21). Names are
    unique within the network collection only."""

    name: str
    tier: TemplateTier
    description: str  # the library-card text
    source_lab: str | None  # user tier: the published lab this entry mirrors
    #                         (LIVE — always the lab's CURRENT stored
    #                         definition). None on builtins.


@dataclass(frozen=True, slots=True)
class NetworkTemplate:
    """`GET /templates/network/{name}` — the entry plus its content: a
    complete netlab definition. Any name/mgmt pinning inside it is
    irrelevant — instantiation goes through the normal lifecycle, where PUT
    re-pins both."""

    name: str
    tier: TemplateTier
    description: str
    source_lab: str | None
    content: str


@dataclass(frozen=True, slots=True)
class NodeTemplate:
    """One node-collection entry (delta 21) — always with content (fragments
    are small and bounded; the builder palette stamps straight from the
    list). `content` is a YAML node-attribute mapping carrying no node name
    (chosen at stamp time)."""

    name: str
    tier: TemplateTier
    description: str
    device: str  # the fragment's `device` (required in the fragment)
    content: str


# --------------------------------------------------------------------------- #
# Config-import shapes (delta 22)
# --------------------------------------------------------------------------- #


# Pinned because Twinlab derives it: the quarantine classes — source config
# referencing the PRODUCTION environment rather than the network's own
# behavior, kept but not applied by default. Routing policy / ACLs / QoS /
# non-mgmt VRFs are never quarantined.
QuarantineClass = Literal["mgmt", "auth", "telemetry", "hardware"]
QUARANTINE_CLASSES: Final[tuple[QuarantineClass, ...]] = (
    "mgmt",
    "auth",
    "telemetry",
    "hardware",
)


@dataclass(frozen=True, slots=True)
class ImportSource:
    """One dumped running config for import_network. `device` must be
    import-capable (CatalogDevice.config_import). VyOS accepts both the
    brace format and the flat set form; IOS/IOL the plain running-config
    text. `name` overrides the node name (default: the config's hostname,
    sanitized — the rename lands in NetworkImport.name_map). Bounds: <= 64
    sources per call, <= 512 KiB each."""

    device: str
    content: str
    name: str | None = None


# One wiring entry (delta 23): a list of "node:interface" endpoints — SOURCE
# hostnames and SOURCE interface names, split on the FIRST colon so
# channelized names keep theirs. Endpoint count decides, mirroring netlab's
# own link model: 2 = p2p, 3+ = LAN; all-unaddressed = a `prefix: false` L2
# link (the unnumbered-core case addressing can never see).
type WiringEntry = list[str]


@dataclass(frozen=True, slots=True)
class WiringSuggestion:
    """`POST /import/wiring-suggestion` (delta 23) — the subnet join, demoted
    to ADVICE: proposed wiring derived from the sources' addressing, for a
    client to prefill a wiring editor with. import_network never consumes a
    suggestion implicitly; the caller reviews, edits, and passes the result
    explicitly. `warnings` names what addressing cannot place (unnumbered
    interfaces) — the wires a human must supply."""

    wiring: list[WiringEntry]
    warnings: list["ImportWarning"]


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    """One quarantined block of a node's source config, with why."""

    reason: QuarantineClass
    content: str


@dataclass(frozen=True, slots=True)
class ImportWarning:
    """A named, non-fatal fidelity hazard — never silent."""

    node: str | None  # None = network-level
    message: str


@dataclass(frozen=True, slots=True)
class NetworkImport:
    """`POST /import/network` — the definition factory's output. PURE: no
    lab is touched; compose create_lab -> put_custom_config ->
    update_definition — custom config FIRST, because the definition PUT's
    dry netlab create validates its `config:` references against the lab's
    STORED templates. The definition carries no `name:` and no mgmt
    addressing — the receiving lab's PUT pins both."""

    definition: str
    custom_config: list["ConfigTemplateSpec"]  # ready for put_custom_config
    #   verbatim (delta 27): the carries as node variants of `imported`
    #   (referenced by the definition's `config: [imported]`, {% raw %}-
    #   wrapped) and non-empty quarantines as node variants of
    #   `imported_quarantine` — unreferenced but attachable per node
    interface_map: dict[str, dict[str, str]]  # node -> {source-if: lab-if}
    name_map: dict[str, str]  # source hostname -> sanitized node name
    quarantine: dict[str, list[QuarantineEntry]]
    warnings: list[ImportWarning]


@dataclass(frozen=True, slots=True)
class NodeImport:
    """`POST /import/node` — one config into a node-template-style fragment
    plus its carry. QUIRK: a single config has no peers to subnet-join, so
    the carry keeps SOURCE interface names; the network flow is the
    fidelity-complete path."""

    fragment: str
    config: str  # the carried config — un-rewritten, {% raw %}-wrapped
    interfaces: dict[str, str | None]  # source ifname -> ipv4 CIDR (None =
    #                                    unnumbered/L2-only)
    quarantine: list[QuarantineEntry]
    warnings: list[ImportWarning]


@dataclass(frozen=True, slots=True)
class DiffSource:
    """One node's source config for config_diff. No device: a diff source
    names a LAB node; the device comes from the lab's definition."""

    node: str
    content: str
    # Delta 23: source-if -> lab-if entries that OVERRIDE/extend the
    # address-join recompute. L2-linked interfaces carry no address on either
    # side, so the join cannot map them — feed back the map import_network
    # returned (the diff stays stateless).
    interface_map: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class NodeConfigDiff:
    """One node's fidelity classification — every source line accounted for."""

    node: str
    matched: int  # source lines present in the running config (post-map)
    missing: list[str]  # source lines ABSENT from the running config
    extra: list[str]  # running-config lines with no source counterpart —
    #                    expected noise (lab baseline, NOS defaults)
    quarantined: int  # source lines excluded from comparison by class


@dataclass(frozen=True, slots=True)
class ConfigDiffReport:
    """`POST /labs/{name}/config-diff` — the import-fidelity proof.
    Informational, never a gate."""

    nodes: list[NodeConfigDiff]


# --------------------------------------------------------------------------- #
# Health shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Liveness:
    status: Literal["ok"]


@dataclass(frozen=True, slots=True)
class Readiness:
    """`GET /health/ready` — same body on 200 and 503 (degraded is data).
    Check values are "ok" or the failure message."""

    status: ReadinessStatus
    checks: dict[str, str]


# --------------------------------------------------------------------------- #
# Lab shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LabNodeState:
    """Live per-node state from clab-api (best-effort)."""

    name: str  # short node name, e.g. "r1"
    container: str  # "clab-<lab>-<node>"
    image: str
    state: ContainerState
    mgmt_ip: str  # bare IP (CIDR stripped); "" when none


@dataclass(frozen=True, slots=True)
class LabSummary:
    """One row of `GET /labs`. `status` is the durable record. `nodes` counts
    the containers present in live state (any state; 0 when down or clab-api
    unreachable); `nodes_running` the subset actually running — after a host
    reboot a lab can be present-but-exited (e.g. 7/0). `permissions` =
    caller's effective set on THIS lab (global + grants + owner-implicit),
    masked to the lab-scoped permission set — global-only perms ride on
    /auth/me."""

    name: str
    status: LabStatus
    owner: Principal | None
    created_at: datetime
    updated_at: datetime
    nodes: int
    nodes_running: int
    config_time_status: ConfigTimeStatus
    # Delta 19: True when the stored definition no longer matches the deployed
    # snapshot. None when nothing is running to drift from (status !=
    # "deployed") or the snapshot is unknown (deployed before the feature).
    # A hint, never a gate — deploy/configure stay allowed.
    definition_drifted: bool | None
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class LabDetail:
    """`GET /labs/{name}`: stored record + live nodes. `definition` is the
    lab's source of truth — None until authored (a "created" lab)."""

    name: str
    status: LabStatus
    definition: str | None  # None only while status="created"
    # Delta 19: the definition of the last SUCCESSFUL deploy, exactly as
    # deployed — what the running environment was built from, so a client can
    # render WHAT changed since deploy. None until first deployed and after
    # destroy. Drift is exact text comparison against `definition`; PUT
    # normalizes the stored text (YAML re-dump), so cosmetic edits don't flag.
    deployed_definition: str | None
    definition_drifted: bool | None  # delta 19 — see LabSummary
    owner: Principal | None
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]
    config_time_status: ConfigTimeStatus
    permissions: set[str]
    # Delta 21: True while this lab is published as a network template (the
    # set_lab_template toggle). Detail-only — the library view is
    # list_network_templates.
    template_published: bool
    # The definition's top-level `message:` — the author's "how to use this
    # lab" note (surfaced instead of silently dropped; up-parity gap 7).
    message: str | None


@dataclass(frozen=True, slots=True)
class NodeConfigResult:
    """Per-node outcome of a config push (from Ansible's PLAY RECAP)."""

    node: str
    status: NodeConfigStatus
    changed: int
    failed: int


@dataclass(frozen=True, slots=True)
class DeployResponse:
    """Terminal `result` of a deploy Job.

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
    # Non-fatal image pre-flight findings (a missing-but-pullable image, or
    # the check skipped because the runner was unreachable). A missing image
    # of a local-only device fails the job (`image_missing`) instead.
    warnings: list[str]


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

    status: DestroyStatus
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
    """One node's interface inventory, keyed by SHORT node name."""

    node: str
    interfaces: list[NodeInterface]


@dataclass(frozen=True, slots=True)
class Duration:
    """A netem duration as a structured {value, unit} pair; the author's unit
    choice is preserved."""

    value: float
    unit: DurationUnit


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


@dataclass(frozen=True, slots=True)
class NetemAction:
    """THE impairment spelling (delta 24): `set_netem` applies one,
    `apply_actions` applies a list — the same object either way. States the
    interface's COMPLETE desired impairment (REPLACE semantics); every
    dimension None = clear the interface. jitter requires delay;
    loss/corruption are percentages, rate kbit/s."""

    node: str  # SHORT node name
    interface: str  # container-side name — what interfaces()/links() report
    delay: Duration | None = None
    jitter: Duration | None = None
    loss: float | None = None
    rate: int | None = None
    corruption: float | None = None


@dataclass(frozen=True, slots=True)
class PowerAction:
    """One power item of a batch (delta 24): node_power's path pair as fields.
    The standalone verb keeps its two scalars — this exists to put the pair in
    a list."""

    node: str
    action: NodePowerAction


@dataclass(frozen=True, slots=True)
class RuntimeActionResult:
    """One batch item's outcome, INDEX-ALIGNED with the submitted list
    (delta 24). ok=True -> `message` is clab-api's verbatim response and
    `code` is None; ok=False -> `code`/`message` are what the standalone
    verb's error envelope would have carried. A failed item is DATA: the call
    does not raise."""

    ok: bool
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeActionsReport:
    """The batch outcome (delta 24). A 2xx means the batch RAN — success or
    failure per item lives in `results`, never in the HTTP status."""

    results: list[RuntimeActionResult]


@dataclass(frozen=True, slots=True)
class LinkEndpoint:
    """One attachment point of a logical link (delta 14)."""

    node: str  # SHORT node name — matches /interfaces keys and the netem routes
    # Container-side interface name (what /interfaces reports and netem
    # accepts): live-resolved when the lab is deployed; otherwise the generated
    # clab-side name (QUIRK: a renaming kind like cisco IOL settles on deploy).
    interface: str
    ifname: str  # netlab/NOS-side name; == interface when they agree
    ifindex: int  # netlab interface index
    ipv4: str | None  # netlab-assigned CIDR; None on unnumbered/L2-only links
    ipv6: str | None
    # Live oper state passthrough (the same unpinned vocabulary QUIRK as
    # NodeInterface.state); None = unknown. Do NOT read `state != "up"` as down:
    # the vocabulary is unpinned, and an interface with no carrier (a dummy —
    # which is how netlab realizes every stub link) reports the string "unknown"
    # while forwarding perfectly. Prefer the server's `oper_state`, which knows
    # the interface kind this wire does not carry.
    state: str | None
    # Active netem impairment; None = not impaired OR unknown (only meaningful
    # on a live read). Deliberately not folded into oper_state.
    impairment: NetemImpairment | None


@dataclass(frozen=True, slots=True)
class LabLink:
    """One LOGICAL link from the netlab-expanded topology (delta 14): a LAN is
    one link with N endpoints, stubs have one — not clab.yml's physical
    per-member fan-out."""

    index: int  # netlab linkindex — stable within a definition version
    name: str | None  # user-set link name only
    type: str  # netlab's vocabulary, passthrough — not a rendering signal
    prefix_ipv4: str | None
    prefix_ipv6: str | None
    bandwidth: int | None
    mtu: int | None
    oper_state: LinkOperState
    endpoints: list[LinkEndpoint]


@dataclass(frozen=True, slots=True)
class LabLinks:
    """The lab's link table (delta 14). `live` is the honesty flag: False means
    oper state could not be resolved (lab not deployed, or the interface
    inventory was unavailable) and every state is "unknown"."""

    links: list[LabLink]
    live: bool


@dataclass(frozen=True, slots=True)
class LayoutPosition:
    """One canvas element's manual position (delta 19)."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class LayoutGroupStyle:
    """One group's canvas styling (delta 20). Lives on the layout resource,
    not the definition — presentation, shared across users like positions."""

    color: str  # "#rrggbb" (server-enforced)


@dataclass(frozen=True, slots=True)
class LabLayout:
    """The lab's ONE shared manual topology arrangement (delta 19), keyed by
    canvas element id — node names plus frontend pseudo-nodes (LAN hubs),
    OPAQUE to the server — plus per-group styling keyed by group name
    (delta 20). Never validated against the definition: stale keys are
    harmless (readers ignore unknown ids; auto-layout and the client-side
    default palette cover the rest). Empty = nothing saved."""

    positions: dict[str, LayoutPosition]
    groups: dict[str, LayoutGroupStyle]


@dataclass(frozen=True, slots=True)
class LabEvent:
    """One container-lifecycle payload from `GET /events`, carried by the
    named SSE event ``lab``."""

    lab: str
    node: str | None
    action: str  # "create" | "start" | "stop" | "kill" | "die" | "destroy" | ...
    timestamp: str


# `JobEvent`, the stream's other payload, is defined with the job shapes below
# (it is typed by JobKind/JobStatus).


# --------------------------------------------------------------------------- #
# Test-suite shapes
# --------------------------------------------------------------------------- #


PARSE_MODES = ("json", "textfsm")
ParseMode = Literal["json", "textfsm"]

# What interpreter a test command's words are for (delta 28): the transport's
# shell, or the device's own CLI (which the server reaches for you).
COMMAND_MODES = ("shell", "cli")
CommandMode = Literal["shell", "cli"]


@dataclass(frozen=True, slots=True)
class TestExpectation:
    """Exactly ONE of contains/not_contains/matches/compare (server-checked).
    Raw matchers work on unparsed stdout; `compare` asserts over PARSED data
    with napalm-validate's grammar (nested partial match, `_mode: strict`,
    numeric operators, list semantics) and requires the case to declare
    `parse` — and vice versa. Still no expression eval anywhere."""

    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None  # regex, re.search on stdout
    compare: dict[str, object] | None = None  # napalm-validate spec over parsed data


@dataclass(frozen=True, slots=True)
class TestCase:
    """What actually runs on a node: one command and how to judge its output.
    `command` — and every string inside `expect` — may carry Jinja2 templates
    rendered per node against the lab's fact namespace (see `facts()`), whose
    promised core is stable contract while a path through `_extras` is
    netlab-shaped and may drift across netlab releases.

    `mode` (delta 28) names the LANGUAGE the command is written in: "shell"
    (default) sends it verbatim to whatever the transport lands in — for a
    docker-transport device that is the container's shell, NOT the NOS CLI —
    and "cli" declares the device's own CLI, which the server rewrites the
    command to reach. 422 on a device that has no CLI of its own (linux,
    dnsmasq).

    `interactive` runs the command through a real interactive session: a
    persistent netmiko channel on SSH transports (IOS truncates timed
    commands on a one-shot exec channel) and a PTY-backed `docker exec -it`
    on docker transports (delta 28 — a silent no-op there before)."""

    command: str
    expect: TestExpectation
    parse: ParseMode | None = None
    mode: CommandMode = "shell"
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class TestCaseDraft:
    """A case being AUTHORED (delta 31): a `TestCase` whose `expect` is
    optional. That is the only difference, and it is what `dry_run_test_case`
    needs — a stored case must assert something, but a case you are still
    writing need not, because the first question is what the command prints.

    So `parse` without `expect` is legal here and only here: asking to SEE the
    parsed structure is precisely how a `compare` gets written. With an
    `expect` present, the usual both-ways compare/parse coupling applies."""

    command: str
    expect: TestExpectation | None = None
    parse: ParseMode | None = None
    mode: CommandMode = "shell"
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class TestCaseDryRunResult:
    """What one unsaved case did on one node (delta 31).

    `parsed` is the piece no other response carries. A `compare` asserts over
    PARSED data, and a suite run computes that structure, asserts against it
    and discards it — so writing a compare has meant predicting the shape
    TextFSM or `vtysh … json` produces. Here it comes back.

    A parse failure is an ANSWER rather than an error: `parse_error` is set,
    the raw `output` survives and the call succeeds, because seeing what the
    parser choked on is how the case gets fixed. (In a saved run the same
    failure is a TestResult with status "error", correctly — there it breaks
    an assertion that then cannot be made.)

    `status`/`detail`/`diff` are populated ONLY when the draft supplied an
    `expect`. With no expectation there is no outcome, and reporting one would
    answer a question nobody asked."""

    node: str
    device: str  # which CLI adapter and TextFSM platform applied
    command: str  # the RENDERED and ADAPTED command — what actually ran
    output: str  # captured stdout (bounded, like TestResult.output)
    parsed: object | None  # the parse result when `parse` was declared and
    #                        succeeded. Shape is the device's, not Twinlab's.
    parse_error: str | None
    elapsed_ms: int
    status: TestStatus | None = None  # only "pass"/"fail" here — a dry run
    #                                   cannot skip, and could-not-run raises.
    detail: str = ""
    diff: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ValidationTest:
    """Run a case on each target node; poll until it passes. `run` is ONE case
    for every node or a DEVICE-KEYED dict (netlab device names: "vyos", "frr",
    "linux", …) — a node whose device has no case reports "skip". `wait`
    (0-600 s) polls until the expectation holds — the convergence knob.

    The TARGET is three selectors, unioned (delta 32), because a bare node list
    is not edit-proof: add a router and every existing test keeps testing the
    old set, silently.

        ValidationTest(run=case, all_nodes=True)              the whole lab
        ValidationTest(run=case, groups=["core"])             a group's members
        ValidationTest(run=case, nodes=["r1"])                exactly these
        ValidationTest(run=case, groups=["core"], nodes=["x"]) the group, plus x

    At least one must select something. Groups are the definition's own,
    resolved to node names with nesting flattened — see `LabFacts.groups` for
    what a name resolves to. Order is first appearance, so a nodes-only test runs in
    exactly the order it always did."""

    run: TestCase | dict[str, TestCase]
    nodes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    all_nodes: bool = False
    wait: int = 0
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestSuite:
    """Named test group. `stage` controls only *automatic* runs: config-time
    suites run after every configure and gate "config done". Any suite can be
    run manually."""

    tests: dict[str, ValidationTest]
    stage: SuiteStage = "runtime"
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestResult:
    """One (test, node) outcome. "fail" = expectation never held (after
    `wait`); "error" = command couldn't run, render, or parse; "skip" = the
    node's device has no case in a device-keyed test. `command` is the
    RENDERED command; `diff` is napalm-validate's structured report, only
    when a `compare` decided the outcome."""

    test: str
    node: str
    status: TestStatus
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
    config_time_status: ConfigTimeStatus


@dataclass(frozen=True, slots=True)
class LabFacts:
    """The per-node fact namespace test-suite templates render against, keyed
    by SHORT node name — `nodes[n]` is exactly what `nodes.<n>` (and `node`,
    for the executing node) resolves to in a template.

    Each node's dict is PARTITIONED into two tiers:

    * the **promised core**, in place — node identity (`name`, `id`, `device`,
      `hostname`, `role?`, `af`, `module`), `mgmt`, `loopback?`, `interfaces`
      (with `neighbors`), and the `ospf`/`bgp`/`ldp`/`vrfs` subtrees. These
      paths are stable contract: they keep their shape across netlab
      upgrades, because Twinlab absorbs the change if netlab moves one.
    * **`_extras`** — every other key, verbatim, netlab-shaped, with NO
      promises: it may change or vanish with any netlab release, and it
      includes netlab's internal `_`-prefixed bookkeeping. Present per
      object (a node, an interface entry, a protocol subtree each carry
      their own), omitted when empty.

    So `{{ node.ospf.router_id }}` is contract and `{{ node._extras.mtu }}`
    is not — the tier is visible in the path. Absence inside the core is
    MEANINGFUL, never a gap: a `role: host` node has a router id but no
    `loopback` interface, so `loopback` is simply absent.

    Left as untyped dicts on purpose: typing the core would freeze netlab's
    entire node schema into this client, which is what the partition exists
    to avoid. Inspect a real lab's namespace with `facts()`."""

    nodes: dict[str, dict[str, object]]
    # Delta 32: the definition's groups, each resolved to the NODE names it
    # selects, with nesting flattened. Only the groups the definition declares
    # — netlab's own internal bookkeeping groups are never targetable. Empty
    # when the definition declares none. Here rather than a resource of
    # its own because the two are asked for together: templates need the
    # namespace, targets need the groups.
    groups: dict[str, list[str]]


# --------------------------------------------------------------------------- #
# Jobs (async lab operations)
# --------------------------------------------------------------------------- #


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

    `result` is populated only on "succeeded", typed by `kind`:
      deploy -> DeployResponse        configure -> ConfigureResponse
      destroy -> DestroyResponse      suite_run -> SuiteReport

    `request` echoes the submitted parameters verbatim (history/display
    data, not a typed surface).

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
class JobStep:
    """One thing an operation did, recorded as it happened (contract delta 29).

    `code` names the phase from a vocabulary pinned per job kind in the
    contract appendix — deploy runs `host_resources`, `topology_generated`,
    `image_preflight`, `host_prep`, `clab_deploy_started`, `nodes_deployed`,
    `nodes_ready`, `config_push_started`, `config_pushed`, `validation` — and
    `message` carries the detail no vocabulary can anticipate ("7/7 nodes
    ok").

    Steps are a NARRATIVE, not the record: the operation's typed payload stays
    on `Job.result`/`Job.error`, and nothing is derivable only from a step. A
    caller that ignores them entirely loses only readability — which is what
    lets the vocabulary GAIN entries without breaking anyone, so treat an
    unknown `code` as displayable, never as an error."""

    at: datetime
    code: str
    level: JobStepLevel
    message: str


@dataclass(frozen=True, slots=True)
class JobDetail(Job):
    """A job read on its own (`get_job`), which is the only place the step log
    is served. The listings (`list_jobs`, `list_all_jobs`) return plain `Job`:
    they render kind/status/timing, and carrying every job's narrative through
    a fleet-wide poll would be waste.

    Steps arrive OLDEST first and grow while the job runs, so polling a running
    job is how a caller follows an operation's progress."""

    steps: list[JobStep]


@dataclass(frozen=True, slots=True)
class JobEvent:
    """One job-lifecycle payload from `GET /events`, carried by the named SSE
    event ``job``.

    A POKE, not a report: it says which job changed and to what, never the
    job's `result`/`error` — read those with `get_job`. Emitted at submit
    (status "running") and again at the terminal state; `timestamp` is the
    job's `created_at` / `finished_at` respectively.

    NOT a durable log: the stream has no replay (see `TwinlabClient.events`)."""

    lab: str
    job_id: UUID
    kind: JobKind
    status: JobStatus
    timestamp: datetime


# --------------------------------------------------------------------------- #
# Custom-config shapes
# --------------------------------------------------------------------------- #


ConfigTemplateTier = Literal["builtin", "user"]
CONFIG_TEMPLATE_TIERS: Final[tuple[ConfigTemplateTier, ...]] = ("builtin", "user")


@dataclass(frozen=True, slots=True)
class TemplateVariant:
    """One source of a config template (delta 27), scoped by exactly one of
    ``node`` (that one node) / ``device`` (any node of that catalog device
    slug) / neither (universal). The scopes mirror netlab's lookup precedence
    — node beats device beats universal. A builtin variant may carry a
    non-catalog device label (``ios``), which simply applies to no node."""

    source: str
    device: str | None = None
    node: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigTemplate:
    """A custom-config template record: the ``config:`` name a definition
    references, a description (may be empty), its tier, and >=1 scoped
    variants. Applicability is one rule: a template applies to a node if some
    variant matches it (node name, else device, else universal)."""

    name: str
    description: str
    tier: ConfigTemplateTier
    variants: list[TemplateVariant]


@dataclass(frozen=True, slots=True)
class ConfigTemplateSpec:
    """PUT's input shape: a user-tier template — ``ConfigTemplate`` minus
    ``tier`` (everything a caller PUTs is user tier)."""

    name: str
    description: str
    variants: list[TemplateVariant]


@dataclass(frozen=True, slots=True)
class CustomConfigResponse:
    """The lab's whole config-template library, ONE merged list — builtins
    first (identical for every lab), then the lab's user records. The
    netlab-facing fileset is derived server-side and never travels."""

    templates: list[ConfigTemplate]
