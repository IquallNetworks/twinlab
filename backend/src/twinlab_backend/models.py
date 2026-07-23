"""Request/response schemas for the HTTP API."""

from datetime import datetime

from pydantic import BaseModel, Field


class DeployRequest(BaseModel):
    # A netlab definition (YAML). It must name each node's `device` and the
    # `provider`; Twinlab does not default them. An optional top-level `name:`
    # sets the lab's stable identity; when absent, one is generated.
    definition: str = Field(min_length=1)
    # Opt-in config push after deploy. Default False because a bare deploy (nodes
    # up but unconfigured) is a legitimate intent and configuring adds minutes;
    # callers ask for it explicitly.
    configure: bool = False


class UpdateDefinitionRequest(BaseModel):
    # A replacement netlab definition for an existing lab. The lab's identity
    # (its name) is fixed by the record and re-pinned into this definition, so a
    # `name:` here is ignored. Takes effect on the next deploy/redeploy.
    definition: str = Field(min_length=1)


class RedeployRequest(BaseModel):
    # Opt-in config push after the redeploy, mirroring DeployRequest.configure.
    configure: bool = False


class NodeConfigResult(BaseModel):
    node: str
    status: str  # "configured" | "failed"
    changed: int
    failed: int


class DeployResponse(BaseModel):
    status: str  # "deployed" | "configured" | "config_failed"
    lab_name: str
    nodes: list[str]
    # Present only when config push ran (deploy with `configure: true`).
    configuration: list[NodeConfigResult] | None = None


class ConfigureResponse(BaseModel):
    status: str  # "configured" | "config_failed"
    lab_name: str
    configuration: list[NodeConfigResult]


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


class LabDetail(BaseModel):
    """A single lab: its stored definition plus live node state."""

    name: str
    status: str  # "deployed" | "destroyed"
    definition: str
    owner: str | None
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]


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
    node: str  # short node name
    interfaces: list[NodeInterface]


class SaveConfigResponse(BaseModel):
    message: str
    output: str  # per-node save output from containerlab
