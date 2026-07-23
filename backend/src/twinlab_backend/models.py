"""Request/response schemas for the HTTP API."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Suite / test / node identifiers: the same tight, path-safe charset the lab and
# node path params use, so a suite name is a safe URL segment.
_Name = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", min_length=1, max_length=64)
]
# A JSON scalar an expectation can assert equality against (json_path form).
type JsonScalar = str | int | float | bool


class TestExpectation(BaseModel):
    """How a test decides pass/fail from a command's stdout. Exactly one matcher is
    set. Deliberately a constrained, safe set — no arbitrary expression eval (a
    netlab-style expression form is a possible later addition). `contains` /
    `not_contains` are literal substrings; `matches` is a regex; `json_path` parses
    stdout as JSON and asserts a dotted path equals `equals`."""

    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None  # regex, searched against stdout
    json_path: str | None = None  # dotted path into JSON-parsed stdout, e.g. "a.b.0.c"
    equals: JsonScalar | None = None  # required with json_path

    @model_validator(mode="after")
    def _exactly_one_matcher(self) -> "TestExpectation":
        matchers = {
            "contains": self.contains,
            "not_contains": self.not_contains,
            "matches": self.matches,
            "json_path": self.json_path,
        }
        set_matchers = [name for name, value in matchers.items() if value is not None]
        if len(set_matchers) != 1:
            raise ValueError("exactly one of contains/not_contains/matches/json_path is required")
        if self.json_path is not None and self.equals is None:
            raise ValueError("json_path requires equals")
        if self.json_path is None and self.equals is not None:
            raise ValueError("equals is only valid with json_path")
        if self.matches is not None:
            try:
                _ = re.compile(self.matches)
            except re.error as exc:
                raise ValueError(f"matches is not a valid regex: {exc}") from exc
        return self


class ValidationTest(BaseModel):
    """One assertion: run `command` on each of `nodes` and check its stdout against
    `expect`. `wait` polls for a converged result (seconds; 0 = a single attempt),
    which is what lets a config-time convergence check tolerate protocols settling."""

    nodes: list[_Name] = Field(min_length=1)
    command: str = Field(min_length=1)
    expect: TestExpectation
    wait: int = Field(default=0, ge=0, le=600)  # seconds to poll before failing
    description: str = ""


class TestSuite(BaseModel):
    """A named group of tests. `stage` controls only *automatic* execution:
    `config-time` suites also run after a configure and gate "config done";
    `runtime` suites run only on demand. Any suite can be run manually regardless
    of stage."""

    stage: Literal["config-time", "runtime"] = "runtime"
    description: str = ""
    tests: dict[_Name, ValidationTest] = Field(min_length=1)


class TestResult(BaseModel):
    """One (test, node) outcome. `pass`: expectation met. `fail`: command ran but
    the expectation did not hold (after any `wait`). `error`: the command could not
    be run or its output could not be evaluated. `skip` is reserved for future
    "not applicable" cases and unused by today's runner."""

    test: str
    node: str
    status: Literal["pass", "fail", "skip", "error"]
    command: str
    output: str  # captured stdout (may be truncated for display)
    detail: str  # what was expected, or why it errored
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
    config_time_ok: bool | None


class DeployRequest(BaseModel):
    # A netlab definition (YAML). It must name each node's `device` and the
    # `provider`; Twinlab does not default them. An optional top-level `name:`
    # sets the lab's stable identity; when absent, one is generated.
    definition: str = Field(min_length=1)
    # Opt-in config push after deploy. Default False because a bare deploy (nodes
    # up but unconfigured) is a legitimate intent and configuring adds minutes;
    # callers ask for it explicitly.
    configure: bool = False
    # Suites to store on the lab as it is created, so a first deploy+configure can
    # also run its config-time checks. Omitted leaves the lab with no suites.
    test_suites: dict[_Name, TestSuite] | None = None
    # Skip the automatic config-time suites at the end of a configure. Default
    # False: convergence gating is on unless the caller opts out.
    skip_config_time_checks: bool = False


class UpdateDefinitionRequest(BaseModel):
    # A replacement netlab definition for an existing lab. The lab's identity
    # (its name) is fixed by the record and re-pinned into this definition, so a
    # `name:` here is ignored. Takes effect on the next deploy/redeploy.
    definition: str = Field(min_length=1)


class RedeployRequest(BaseModel):
    # Opt-in config push after the redeploy, mirroring DeployRequest.configure.
    configure: bool = False
    # Skip the automatic config-time suites at the end of a configure (see
    # DeployRequest). Redeploy reuses the lab's stored suites.
    skip_config_time_checks: bool = False


class ConfigureRequest(BaseModel):
    # Configure reuses the lab's stored definition and suites; the only knob is
    # whether to skip the automatic config-time checks.
    skip_config_time_checks: bool = False


class NodeConfigResult(BaseModel):
    node: str
    status: str  # "configured" | "failed"
    changed: int
    failed: int


class DeployResponse(BaseModel):
    # "validation_failed": config push succeeded but a config-time suite failed —
    # the lab stays deployed, the failure is explicit here and on the record.
    status: str  # "deployed" | "configured" | "config_failed" | "validation_failed"
    lab_name: str
    nodes: list[str]
    # Present only when config push ran (deploy with `configure: true`).
    configuration: list[NodeConfigResult] | None = None
    # Present only when config-time suites ran (configure, not skipped, suites exist).
    validation: list[SuiteReport] | None = None


class ConfigureResponse(BaseModel):
    status: str  # "configured" | "config_failed" | "validation_failed"
    lab_name: str
    configuration: list[NodeConfigResult]
    validation: list[SuiteReport] | None = None


class DestroyResponse(BaseModel):
    status: str
    detail: str


class LabNodeState(BaseModel):
    """Live node state, read from clab-api at request time (best-effort)."""

    name: str  # short node name, e.g. r1
    container: str  # clab-<lab>-<node>
    image: str
    state: str
    mgmt_ip: str  # bare management IP (CIDR stripped); "" when the node has none


class LabSummary(BaseModel):
    """A lab in a listing. `status` is the durable record's truth; `nodes` is
    the live count from clab-api (0 when the lab isn't currently running or
    clab-api couldn't be reached)."""

    name: str
    status: str  # "deployed" | "destroyed"
    owner: str | None
    created_at: datetime
    updated_at: datetime
    nodes: int
    # Config-time validation gate from the most recent configure: None (not run /
    # skipped / no config-time suites), True (passed), False (failed). Surfaced so
    # a lab whose config-time checks failed is unambiguous in a listing.
    config_time_ok: bool | None


class LabDetail(BaseModel):
    """A single lab: its stored definition plus live node state."""

    name: str
    status: str  # "deployed" | "destroyed"
    definition: str
    owner: str | None
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]
    config_time_ok: bool | None


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
    # clab-api keys the interface inventory by container name (`clab-<lab>-<node>`),
    # not the short node name the rest of the API uses; passed through verbatim.
    node: str
    interfaces: list[NodeInterface]


class SaveConfigResponse(BaseModel):
    message: str
    output: str  # per-node save output from containerlab


class NetemSetRequest(BaseModel):
    """Netem link impairment to apply to one node interface. The node is taken from
    the path; the container it maps to is resolved server-side. Every impairment is
    optional and independent — an omitted field is left unchanged, but at least one
    must be present (an empty set is a no-op we reject). `delay`/`jitter` are netem
    duration strings (e.g. "50ms"); `loss`/`corruption` are percentages; `rate` is
    kbit/s. `jitter` is meaningful only alongside `delay`."""

    interface: str = Field(min_length=1)
    delay: str | None = None
    jitter: str | None = None
    loss: float | None = Field(default=None, ge=0, le=100)
    rate: int | None = Field(default=None, ge=0)  # kbit/s
    corruption: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _require_meaningful_impairment(self) -> "NetemSetRequest":
        if all(v is None for v in (self.delay, self.jitter, self.loss, self.rate, self.corruption)):
            raise ValueError(
                "at least one impairment (delay/jitter/loss/rate/corruption) is required"
            )
        if self.jitter is not None and self.delay is None:
            raise ValueError("jitter requires delay")
        return self


class NetemResetRequest(BaseModel):
    # Clear all impairment from one node interface (the node comes from the path).
    interface: str = Field(min_length=1)


class NetemImpairment(BaseModel):
    """Current netem impairment on one node interface, read from clab-api. Empty
    duration / 0 means that dimension is unshaped."""

    interface: str
    delay: str
    jitter: str
    loss: float  # packet loss, percent
    rate: int  # kbit/s
    corruption: float  # percent


class LabEvent(BaseModel):
    """A lab lifecycle event relayed from clab-api as the SSE payload; the frontend
    invalidates the affected lab's queries on each one."""

    lab: str
    node: str | None
    action: str  # container action: create | start | stop | kill | die | destroy | …
    timestamp: str
