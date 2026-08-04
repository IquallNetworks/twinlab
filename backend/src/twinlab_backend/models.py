"""Request/response schemas for the HTTP API."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Status vocabularies, pinned as Literals so OpenAPI carries them (contract
# delta 3). "created" is the lifecycle split's record-only state.
type LabStatus = Literal["created", "deploying", "deployed", "destroyed"]
type ConfigTimeStatus = Literal["not_run", "passed", "failed"]
type DeployStatus = Literal["deployed", "configured", "config_failed", "validation_failed"]
type ConfigureStatus = Literal["configured", "config_failed", "validation_failed"]
type DestroyStatus = Literal["destroyed", "deleted"]
# Async job vocabularies (contract delta 12). No "pending": there is no queue —
# a job starts at submit or the submit is rejected (409 job_in_flight).
type JobKind = Literal["deploy", "configure", "destroy", "suite_run"]
type JobStatus = Literal["running", "succeeded", "failed"]
# Docker engine's container-state vocabulary; clab-api's passthrough is
# validated against it at the read boundary (an unknown state is a loud 502).
type ContainerState = Literal[
    "created", "running", "paused", "restarting", "removing", "exited", "dead"
]

# Suite / test / node identifiers: the same tight, path-safe charset the lab and
# node path params use, so a suite name is a safe URL segment.
_Name = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", min_length=1, max_length=64)
]
# How a test case turns stdout into data `compare` can assert on (contract
# delta 17): "json" = stdout must parse as JSON (free on VyOS — FRR's vtysh
# emits it natively); "textfsm" = stdout parses into a list of records via a
# TextFSM template resolved from the node's device + the rendered command
# (ntc-templates overlaid by Twinlab-packaged templates). A missing template
# or failed parse is an "error" result — never a silent raw fallback.
type ParseMode = Literal["json", "textfsm"]

# A custom-config template path: a relative, traversal-free `.j2` path (flat like
# `nat.j2` or per-device like `nat/ios.j2`). The runner enforces the same contract
# at its write boundary; keeping it here rejects a bad path before it is stored.
_TemplatePath = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.j2$", min_length=1, max_length=128),
]
# A fileset of custom-config templates: path -> Jinja source.
type CustomConfigFileset = dict[_TemplatePath, str]


class TestExpectation(BaseModel):
    """How a test case decides pass/fail (contract delta 17). Exactly one matcher
    is set. The raw matchers work on unparsed stdout: `contains`/`not_contains`
    are literal substrings, `matches` is a regex. `compare` asserts over PARSED
    data with napalm-validate's grammar (nested partial match by default,
    `_mode: strict` for exhaustiveness, numeric operators like "<15" /
    "10<->20" / "5%10", `list` semantics) — a compare spec is data, never
    expression eval. The compare ⟺ parse pairing is checked on TestCase, the
    first place both fields exist."""

    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None  # regex, searched against stdout
    compare: dict[str, object] | None = None  # napalm-validate spec over parsed data

    @model_validator(mode="after")
    def _exactly_one_matcher(self) -> TestExpectation:
        matchers = {
            "contains": self.contains,
            "not_contains": self.not_contains,
            "matches": self.matches,
            "compare": self.compare,
        }
        set_matchers = [name for name, value in matchers.items() if value is not None]
        if len(set_matchers) != 1:
            raise ValueError("exactly one of contains/not_contains/matches/compare is required")
        if self.matches is not None:
            try:
                _ = re.compile(self.matches)
            except re.error as exc:
                raise ValueError(f"matches is not a valid regex: {exc}") from exc
        return self


class TestCase(BaseModel):
    """What actually runs on a node (contract delta 17): one command and how to
    judge its output. `command` — and every string inside `expect` — may carry
    Jinja2 templates rendered per executing node against the lab's fact
    namespace (`node` / `nodes.<name>`, see GET /labs/{name}/facts).
    `interactive` routes the exec through a persistent CLI channel when the
    node's transport is SSH (IOS truncates timed commands like `ping ...
    repeat` on a one-shot exec channel); it is a deliberate no-op over docker
    exec, which already captures everything."""

    command: str = Field(min_length=1)
    expect: TestExpectation
    parse: ParseMode | None = None
    interactive: bool = False

    @model_validator(mode="after")
    def _compare_requires_parse(self) -> TestCase:
        if (self.expect.compare is not None) != (self.parse is not None):
            raise ValueError(
                "compare and parse go together: compare asserts over parsed data, "
                "and parsed data is only asserted with compare"
            )
        return self


class ValidationTest(BaseModel):
    """One assertion: run a case on each of `nodes` and check the outcome.
    `run` is ONE case for every node or a DEVICE-KEYED dict (netlab device
    names: "vyos", "iol", "linux", ...) — case-level keying (delta 17): each
    node picks its device's complete recipe, and a node whose device has no
    case reports `skip`, not an error. `wait` polls for a converged result
    (seconds; 0 = a single attempt) — the convergence knob."""

    nodes: list[_Name] = Field(min_length=1)
    run: TestCase | dict[_Name, TestCase]
    wait: int = Field(default=0, ge=0, le=600)  # seconds to poll before failing
    description: str = ""

    @model_validator(mode="after")
    def _device_keyed_run_not_empty(self) -> ValidationTest:
        if isinstance(self.run, dict) and not self.run:
            raise ValueError("a device-keyed run needs at least one case")
        return self


class TestSuite(BaseModel):
    """A named group of tests. `stage` controls only *automatic* execution:
    `config-time` suites also run after a configure and gate "config done";
    `runtime` suites run only on demand. Any suite can be run manually regardless
    of stage."""

    stage: Literal["config-time", "runtime"] = "runtime"
    description: str = ""
    tests: dict[_Name, ValidationTest] = Field(min_length=1)


class TestResult(BaseModel):
    """One (test, node) outcome. `pass`: expectation met. `fail`: the command ran
    but the expectation did not hold (after any `wait`). `error`: the command
    could not run, render, or parse. `skip`: the node's device has no case in a
    device-keyed test. `command` is the RENDERED command (what actually ran);
    `diff` is napalm-validate's structured complies/present/missing/extra
    report, populated only when a `compare` decided the outcome."""

    test: str
    node: str
    status: Literal["pass", "fail", "skip", "error"]
    command: str
    output: str  # captured stdout (may be truncated for display)
    detail: str  # what was expected, or why it errored
    diff: dict[str, object] | None = None
    elapsed_ms: int


class SuiteReport(BaseModel):
    suite: str
    stage: str
    passed: int
    failed: int
    skipped: int
    errored: int
    ran_at: datetime
    results: list[TestResult]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.errored == 0


class UpdateTestSuitesRequest(BaseModel):
    # Replace a lab's whole suite set. Stored on the record, never sent to
    # `netlab create`, so it can't trip netlab's topology attribute validation.
    test_suites: dict[_Name, TestSuite]


class TestSuitesResponse(BaseModel):
    """A lab's declared suites plus the last run of each (keyed by suite name;
    empty when never run) and the config-time gate result from the most recent
    configure (None = not run / skipped)."""

    test_suites: dict[str, TestSuite]
    last_validation: dict[str, SuiteReport]
    config_time_status: ConfigTimeStatus


class LabFactsResponse(BaseModel):
    """The per-node fact namespace test-suite templates render against (contract
    delta 17), keyed by SHORT node name. PROVISIONAL: values are netlab's raw
    node dicts from the expanded topology, deliberately unpinned until a stable
    subset is chosen (pre-v1.0) — this endpoint is the discoverability and
    insulation layer for that decision."""

    nodes: dict[str, dict[str, object]]


class BuiltinTemplateOut(BaseModel):
    """A built-in custom-config template as the API exposes it: the `config:` name,
    a description, and its per-device source files. Read-only (non-deletable)."""

    name: str
    description: str
    files: dict[str, str]


class UpdateCustomConfigRequest(BaseModel):
    # Replace a lab's user-defined template fileset. Stored on the record, never
    # sent to `netlab create`. Paths are validated (relative, .j2) and may not
    # shadow a built-in (rejected with 409).
    custom_config: CustomConfigFileset


class CustomConfigResponse(BaseModel):
    """A lab's custom config: the shipped built-in library (read-only) plus the
    lab's own user-defined templates ({relpath: source}, editable)."""

    builtin: list[BuiltinTemplateOut]
    custom_config: dict[str, str]


class CreateLabRequest(BaseModel):
    # The lab's stable, durable identity, chosen by the caller — it keys the
    # record and every `/labs/{name}` route, and is later pinned into the
    # authored definition. Create is record-only (lifecycle split): it
    # allocates the mgmt subnet and stores nothing else; the definition is
    # authored via PUT and deployed via POST /labs/{name}/deploy.
    name: _Name


class UpdateDefinitionRequest(BaseModel):
    # A replacement netlab definition for a lab (also the FIRST authoring step
    # after create). The lab's identity (its name) is fixed by the record and
    # re-pinned into this definition, so a `name:` here is ignored. Takes
    # effect on the next deploy.
    definition: str = Field(min_length=1)


class DeployLabRequest(BaseModel):
    # Opt-in config push after the deploy. Default False because a bare deploy
    # (nodes up but unconfigured) is a legitimate intent and configuring adds
    # minutes; callers ask for it explicitly.
    configure: bool = False
    # Skip the automatic config-time suites at the end of a configure. Default
    # False: convergence gating is on unless the caller opts out. Deploy reuses
    # the lab's stored suites and custom config.
    skip_config_time_checks: bool = False


class ConfigureRequest(BaseModel):
    # Configure reuses the lab's stored definition and suites; the only knob is
    # whether to skip the automatic config-time checks.
    skip_config_time_checks: bool = False


class NodeConfigResult(BaseModel):
    node: str
    status: Literal["configured", "failed"]
    changed: int
    failed: int


class DeployResponse(BaseModel):
    # "validation_failed": config push succeeded but a config-time suite failed —
    # the lab stays deployed, the failure is explicit here and on the record.
    status: DeployStatus
    lab_name: str
    nodes: list[str]
    # Present only when config push ran (deploy with `configure: true`).
    configuration: list[NodeConfigResult] | None = None
    # Present only when config-time suites ran (configure, not skipped, suites exist).
    validation: list[SuiteReport] | None = None


class ConfigureResponse(BaseModel):
    status: ConfigureStatus
    lab_name: str
    configuration: list[NodeConfigResult]
    validation: list[SuiteReport] | None = None


class DestroyResponse(BaseModel):
    status: DestroyStatus
    detail: str


class JobErrorOut(BaseModel):
    """Why a job FAILED — the error envelope with a status classifier.
    `status_code` uses HTTP vocabulary (422 netlab_invalid, 502
    upstream_error, ...) so error handling matches on the same codes
    everywhere; it is never an actual response status (job reads are 200)."""

    status_code: int
    code: str
    message: str
    extras: dict[str, object]


class JobOut(BaseModel):
    """One async lab operation (contract delta 12). `result` is set only on
    "succeeded" and is the operation's payload, typed by `kind` on the wire
    contract (DeployResponse / ConfigureResponse / DestroyResponse /
    SuiteReport); served as stored. failed = could-not-run — an operation
    that ran with a bad outcome (config_failed / validation_failed) is a
    SUCCEEDED job whose result.status says so."""

    id: uuid.UUID
    lab_name: str
    kind: JobKind
    status: JobStatus
    request: dict[str, object]
    result: dict[str, object] | None = None
    error: JobErrorOut | None = None
    created_at: datetime
    finished_at: datetime | None = None


class Principal(BaseModel):
    """A user or group as referenced in responses: id + display name."""

    id: uuid.UUID
    name: str


class LabOwnerOut(BaseModel):
    """`PUT /labs/{name}/owner` response (contract delta 8 — its own shape,
    not a repurposed grant)."""

    lab: str
    owner: Principal


class LabNodeState(BaseModel):
    """Live node state, read from clab-api at request time (best-effort)."""

    name: str  # short node name, e.g. r1
    container: str  # clab-<lab>-<node>
    image: str
    state: ContainerState
    mgmt_ip: str  # bare management IP (CIDR stripped); "" when the node has none


class LabSummary(BaseModel):
    """A lab in a listing. `status` is the durable record's truth. `nodes`
    counts the containers PRESENT in clab-api's live state (any state; 0 when
    the lab is down or clab-api couldn't be reached); `nodes_running` the
    subset actually running — after a host reboot a lab can be
    present-but-exited (e.g. 7/0)."""

    name: str
    status: LabStatus
    owner: Principal | None
    created_at: datetime
    updated_at: datetime
    nodes: int
    nodes_running: int
    # Config-time validation gate from the most recent configure. A skipped
    # gate RETAINS the previous result; "no config-time suites" = "not_run".
    config_time_status: ConfigTimeStatus
    # Delta 19: True when the stored definition no longer matches the deployed
    # snapshot. None when nothing is running to drift from (status !=
    # "deployed") or the snapshot is unknown (a lab deployed before the
    # feature). A HINT, never a gate — deploy/configure stay allowed.
    definition_drifted: bool | None
    # The caller's effective permissions on this lab, MASKED to the lab-scoped
    # set (contract delta 10) — global-only perms ride on /auth/me. Lets the
    # list gate per-row actions without assuming a global permission.
    permissions: list[str]


class LabDetail(BaseModel):
    """A single lab: its stored record plus live node state. `definition` is
    None only while status is "created" (not yet authored). `permissions` is
    the caller's effective set *on this lab* (owner-implicit + global + per-lab
    grants), masked to the lab-scoped permissions (contract delta 10)."""

    name: str
    status: LabStatus
    definition: str | None
    # Delta 19: the definition of the last successful deploy, exactly as
    # deployed — served (not just the derived flag) so a client can render
    # WHAT changed since deploy. None until first deployed / after destroy.
    deployed_definition: str | None
    definition_drifted: bool | None  # delta 19 — see LabSummary
    owner: Principal | None
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]
    config_time_status: ConfigTimeStatus
    permissions: list[str]
    # Delta 21: True while this lab is published as a network template (the
    # PUT /labs/{name}/template toggle). Detail-only — the library view is
    # GET /templates/network, not the labs list.
    template_published: bool


class LayoutPosition(BaseModel):
    """One canvas element's manual position (contract delta 19). Finite floats
    only — NaN/inf round-trip poorly through JSON and mean a broken writer,
    not a layout."""

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


# Canvas element ids are OPAQUE presentation data (node names plus frontend
# pseudo-nodes like LAN hubs), so validation is shape-only. 128 chars sits far
# above the 64-char node-name cap while bounding the row.
_LayoutKey = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class LayoutGroupStyle(BaseModel):
    """One group's canvas styling (contract delta 20). On the layout resource,
    not the definition — netlab's attribute validation rejects unknown group
    keys, and the definition is the deployable source of truth, not a
    stylesheet."""

    # Pinned to hex so the value is portable and can't smuggle arbitrary CSS
    # into whatever inline style a consumer builds from it.
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class LabLayoutResponse(BaseModel):
    """The lab's ONE shared manual topology arrangement (delta 19), keyed by
    canvas element id, plus per-group styling keyed by group name (delta 20).
    Never validated against the definition: stale keys (a renamed node, a
    reindexed link, a deleted group) are harmless — readers ignore unknown
    ids and auto-layout/default palette cover the rest. Empty = nothing
    saved."""

    positions: dict[str, LayoutPosition]
    groups: dict[str, LayoutGroupStyle]


class PutLayoutRequest(BaseModel):
    """Full REPLACE of the stored layout resource — positions AND group
    styles ({} clears — no separate DELETE)."""

    # 512 elements bounds the row far above any real canvas (labs are tens of
    # nodes, not hundreds).
    positions: dict[_LayoutKey, LayoutPosition] = Field(max_length=512)
    # Delta 20: explicit styling choices only (unstyled groups render a
    # client-side default). Defaults empty for delta-19 callers — the PUT
    # still replaces the WHOLE resource, so such a caller clears any styles.
    groups: dict[_LayoutKey, LayoutGroupStyle] = Field(default_factory=dict, max_length=512)


# Template library (contract delta 21). Two sibling collections with
# independent namespaces: /templates/network (complete definitions) and
# /templates/node (single-node fragments). Tier "builtin" is shipped read-only;
# "user" is authored at runtime (network: a published lab, served live; node:
# stored rows).
type TemplateTier = Literal["builtin", "user"]


class NetworkTemplateSummary(BaseModel):
    """One network-collection entry, content omitted. `source_lab` names the
    published lab a user-tier entry mirrors (live — the entry always serves
    that lab's CURRENT stored definition); None on builtins."""

    name: str
    tier: TemplateTier
    description: str
    source_lab: str | None


class NetworkTemplateOut(NetworkTemplateSummary):
    """The entry with its content: a complete netlab definition. Whatever
    name/mgmt pinning the text carries is irrelevant — instantiation goes
    through the normal lifecycle, where PUT re-pins both."""

    content: str


class NodeTemplateOut(BaseModel):
    """One node-collection entry — always with content (fragments are small
    and bounded; the builder palette stamps straight from the list)."""

    name: str
    tier: TemplateTier
    description: str
    device: str  # denormalized from the fragment for catalog-style rendering
    content: str


class NodeTemplateCreate(BaseModel):
    """POST /templates/node. `content` is structurally validated by the route
    (parseable YAML mapping naming `device`) — 422 invalid_template, not a
    schema error, so the message can say what is wrong with the fragment."""

    name: _Name
    description: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class NodeTemplateUpdate(BaseModel):
    """PUT /templates/node/{name}: full replace of description + content (the
    name is the identity and does not change)."""

    description: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class LabTemplateSet(BaseModel):
    """PUT /labs/{name}/template — the publish toggle. The description is the
    library-card text: required when publishing, ignored when withdrawing."""

    published: bool
    description: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _description_when_publishing(self) -> LabTemplateSet:
        if self.published and self.description is None:
            raise ValueError("description is required when publishing")
        return self


class LabActionResponse(BaseModel):
    """Result of a node/lab lifecycle action (start/stop/restart): clab-api's
    status message, passed through."""

    message: str


class NodeLogsResponse(BaseModel):
    node: str  # short node name
    container: str  # clab-<lab>-<node>
    logs: str


class NodeInterface(BaseModel):
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str  # clab-api's interface `type`, renamed off the builtin


class NodeInterfaces(BaseModel):
    # Keyed by the SHORT node name (contract delta 6) — the backend translates
    # from clab-api's container-name keys.
    node: str
    interfaces: list[NodeInterface]


class SaveConfigResponse(BaseModel):
    message: str
    output: str  # per-node save output from containerlab


class Duration(BaseModel):
    """A netem duration as a structured {value, unit} pair (contract delta 7);
    the author's unit choice is preserved."""

    value: float = Field(ge=0)
    unit: Literal["us", "ms", "s"]


class NetemSetRequest(BaseModel):
    """Netem link impairment for one node interface (the node comes from the
    path; its container is resolved server-side). REPLACE semantics (contract
    delta 7): the body states the interface's COMPLETE desired impairment — an
    omitted/None dimension is cleared, and a body with no impairments clears
    everything (subsuming the old /netem/reset). `loss`/`corruption` are
    percentages; `rate` is kbit/s; `jitter` is meaningful only with `delay`."""

    interface: str = Field(min_length=1)
    delay: Duration | None = None
    jitter: Duration | None = None
    loss: float | None = Field(default=None, ge=0, le=100)
    rate: int | None = Field(default=None, ge=0)  # kbit/s
    corruption: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _jitter_requires_delay(self) -> NetemSetRequest:
        if self.jitter is not None and self.delay is None:
            raise ValueError("jitter requires delay")
        return self


# Per-node power controls (contract delta 24 moved this here from api/labs.py:
# the batch items and the single route share ONE vocabulary). clab-api adds
# pause/unpause on top of the lab-level set.
type NodeAction = Literal["start", "stop", "restart", "pause", "unpause"]


class NetemActionItem(NetemSetRequest):
    """One netem item of a batch (contract delta 24). The wire identity the
    contract pins: the single route's body (inherited verbatim — same fields,
    same bounds, same jitter-requires-delay rule) plus its address (`node`,
    which the single route takes from the path) plus the `kind` tag."""

    kind: Literal["netem"]
    node: _Name


class PowerActionItem(BaseModel):
    """One power item of a batch (contract delta 24): the single node-power
    route's PATH PAIR materialized as fields."""

    kind: Literal["power"]
    node: _Name
    action: NodeAction


# Discriminated on `kind` so a malformed item names the field that is wrong
# rather than reporting five union-member failures.
type RuntimeActionItem = Annotated[NetemActionItem | PowerActionItem, Field(discriminator="kind")]


class RuntimeActionsRequest(BaseModel):
    """A batch of runtime actions (contract delta 24). Items execute
    SEQUENTIALLY in request order and execution continues past a failed item;
    ordering is the caller's to compose. Bounded at 64 — the batch is
    synchronous, and each item can cost a live clab-api round trip. An empty
    batch is a caller bug, not a no-op."""

    actions: list[RuntimeActionItem] = Field(min_length=1, max_length=64)


class RuntimeActionResult(BaseModel):
    """One item's outcome, index-aligned with the request (contract delta 24).
    ok=True -> `message` is clab-api's verbatim response and `code` is None;
    ok=False -> `code`/`message` are what the standalone verb's error envelope
    would have carried. A failed item is DATA: the batch still returns 2xx."""

    ok: bool
    code: str | None = None
    message: str


class RuntimeActionsReport(BaseModel):
    """The batch outcome (contract delta 24). A 2xx means the batch RAN — each
    item's success or failure lives in `results`, never in the HTTP status."""

    results: list[RuntimeActionResult]


class NetemImpairment(BaseModel):
    """Current netem impairment on one node interface, read from clab-api.
    None / 0 means that dimension is unshaped."""

    interface: str
    delay: Duration | None
    jitter: Duration | None
    loss: float  # packet loss, percent
    rate: int  # kbit/s
    corruption: float  # percent


# Contract delta 14. Pinned — unlike the interface `state` passthrough —
# because Twinlab derives this value itself. Roll-up over the link's endpoint
# states: all "up" -> "up"; all known-not-up -> "down"; a mix of known states
# -> "degraded"; any endpoint unknown -> "unknown".
LinkOperState = Literal["up", "degraded", "down", "unknown"]


class LinkEndpoint(BaseModel):
    """One attachment point of a logical link (contract delta 14)."""

    node: str  # SHORT node name — matches /interfaces keys and the netem routes
    # The container-side interface name: what /interfaces reports and netem
    # accepts. Resolved against the live inventory (name-or-alias match) when
    # the lab is deployed; undeployed it is the generated clab-side name.
    interface: str
    ifname: str  # netlab/NOS-side name; == interface when they agree
    ifindex: int  # netlab interface index
    ipv4: str | None  # netlab-assigned CIDR; None on unnumbered/L2-only links
    ipv6: str | None
    # Live oper state passthrough for this interface (the same unpinned
    # vocabulary as NodeInterface.state); None = unknown.
    state: str | None
    # Active netem impairment on this interface; None = not impaired OR
    # unknown (only meaningful on a live read). Deliberately not folded into
    # oper_state — an impairment is requested behavior, not degraded health.
    impairment: NetemImpairment | None


class LabLink(BaseModel):
    """One LOGICAL link from the netlab-expanded topology (contract delta 14):
    a LAN is one link with N endpoints, stubs have one — not clab.yml's
    physical per-member fan-out."""

    index: int  # netlab linkindex — stable within a definition version
    name: str | None  # user-set link name only
    # netlab's link type — a passthrough, not pinned (netlab owns the
    # vocabulary) and not a rendering signal: discriminate on len(endpoints).
    type: str
    prefix_ipv4: str | None  # the link subnet — the only IP surface we have
    prefix_ipv6: str | None  # (/interfaces is L2-only)
    bandwidth: int | None
    mtu: int | None
    oper_state: LinkOperState
    endpoints: list[LinkEndpoint]


class LabLinksResponse(BaseModel):
    """The lab's link table (contract delta 14). `live` is the honesty flag:
    False means oper state could not be resolved (lab not deployed, or the
    interface inventory was unavailable) and every state is "unknown"."""

    links: list[LabLink]
    live: bool


class LabEvent(BaseModel):
    """A lab lifecycle event relayed from clab-api, carried by the SSE stream's
    named `lab` event; the frontend invalidates the affected lab's queries on
    each one."""

    lab: str
    node: str | None
    action: str  # container action: create | start | stop | kill | die | destroy | …
    timestamp: str


class JobEvent(BaseModel):
    """A job lifecycle event (contract delta 16), carried by the SSE stream's
    named `job` event: one at submit (status "running"), one at the terminal
    state.

    A POKE, not a report — no result/error, which are typed by kind and read
    with `GET /labs/{lab}/jobs/{job_id}`. `timestamp` is the job's created_at
    or finished_at, so the event carries the same instant the record does."""

    lab: str
    job_id: uuid.UUID
    kind: JobKind
    status: JobStatus
    timestamp: datetime
