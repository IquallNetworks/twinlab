"""Client for the netlab-runner sidecar.

The runner owns config push: `POST /configure {definition}` runs `netlab create`
+ `netlab initial` (Ansible over the docker connection) and returns per-node
results. The definition must carry a stable `name:` so the runner's regenerated
inventory targets the containers clab-api deployed.

httpx2 is a third-party boundary: its exceptions and the runner's JSON are
translated here into typed results; nothing propagates as an exception.
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

import httpx2
from pydantic import BaseModel, ValidationError

from twinlab_backend.result import Err, Ok, Result

# netlab create + Ansible push blocks until every node is configured; for several
# nodes this runs into minutes, well past the client default.
_CONFIGURE_TIMEOUT_SECONDS = 600.0
# One validation exec is a single show command; keep headroom for a cold-cache
# `netlab create` on the first check of a lab, then it is quick.
_EXEC_TIMEOUT_SECONDS = 120.0
# Readiness polls each node's SSH/console until the NOS boots. netlab bounds the
# wait per device (`netlab_check_retries * netlab_check_delay`, nodes concurrent —
# up to 600s for the slowest device it ships); the runner caps the subprocess at
# 900s as a backstop. This must stay above that cap so the HTTP call outlives it
# and the runner's own error is what surfaces.
_READY_TIMEOUT_SECONDS = 960.0
# A local docker CLI read; outlive the runner's own 30s subprocess cap.
_IMAGES_TIMEOUT_SECONDS = 40.0
# `/system/df` walks every image, volume and build-cache record; the runner caps
# it at 60s, so stay above that and let the runner's own error surface.
_DOCKER_USAGE_TIMEOUT_SECONDS = 70.0
# Per-container stats cost ~1s of daemon-side sampling each, but the runner runs
# them concurrently — so this is one sample's wait plus headroom, not per node.
_DOCKER_STATS_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RunnerError:
    # "bad_definition" (422) | "runner" (5xx) | "transport"
    reason: str
    message: str


@dataclass(frozen=True, slots=True)
class NodeConfig:
    node: str
    changed: int
    failed: int

    @property
    def status(self) -> Literal["configured", "failed"]:
        return "failed" if self.failed else "configured"


@dataclass(frozen=True, slots=True)
class ConfigureReport:
    lab_name: str
    succeeded: bool
    nodes: tuple[NodeConfig, ...]


class _NodeResult(BaseModel):
    node: str
    changed: int
    failed: int


class _ConfigureResponse(BaseModel):
    lab_name: str
    succeeded: bool
    nodes: list[_NodeResult]


class _ExecResponse(BaseModel):
    node: str
    stdout: str


class _ImagesResponse(BaseModel):
    images: list[str]


@dataclass(frozen=True, slots=True)
class DiskEntry:
    kind: str
    total: int
    active: int
    size_bytes: int
    reclaimable_bytes: int


@dataclass(frozen=True, slots=True)
class DockerUsage:
    root_dir: str
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: tuple[DiskEntry, ...]


class _DiskEntryResponse(BaseModel):
    kind: str
    total: int
    active: int
    size_bytes: int
    reclaimable_bytes: int


class _DockerUsageResponse(BaseModel):
    root_dir: str
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: list[_DiskEntryResponse]


@dataclass(frozen=True, slots=True)
class ContainerStats:
    """Every measure is nullable: the daemon answers for a stopped container
    with an empty payload, and 0% would claim an idle container where there is
    no running one."""

    container: str
    cpu_percent: float | None
    memory_bytes: int | None
    memory_limit_bytes: int | None
    net_rx_bytes: int | None
    net_tx_bytes: int | None
    pids: int | None


class _ContainerStatsResponse(BaseModel):
    container: str
    cpu_percent: float | None
    memory_bytes: int | None
    memory_limit_bytes: int | None
    net_rx_bytes: int | None
    net_tx_bytes: int | None
    pids: int | None


class _StatsResponse(BaseModel):
    stats: list[_ContainerStatsResponse]


@dataclass(frozen=True, slots=True)
class ReadyReport:
    ready: bool


class _ReadyResponse(BaseModel):
    ready: bool


@dataclass(frozen=True, slots=True)
class RunnerClient:
    client: httpx2.AsyncClient
    base_url: str

    async def configure(
        self, definition: str, templates: dict[str, str]
    ) -> Result[ConfigureReport, RunnerError]:
        """Render and push a lab's config. `templates` is the custom-config fileset
        (built-in library merged with the lab's user templates); the runner writes
        it into its workdir so `netlab initial` deploys whichever the definition
        references. Pass an empty map for a lab with no custom config."""
        try:
            resp = await self.client.post(
                f"{self.base_url}/configure",
                json={"definition": definition, "templates": templates},
                timeout=_CONFIGURE_TIMEOUT_SECONDS,
            )
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"configure request failed: {exc}"))

        if resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            return Err(RunnerError("bad_definition", resp.text))
        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"configure rejected: {resp.text}"))

        try:
            parsed = _ConfigureResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected configure response: {exc}"))

        return Ok(
            ConfigureReport(
                lab_name=parsed.lab_name,
                succeeded=parsed.succeeded,
                nodes=tuple(
                    NodeConfig(node=n.node, changed=n.changed, failed=n.failed)
                    for n in parsed.nodes
                ),
            )
        )

    async def ready(
        self, definition: str, templates: dict[str, str]
    ) -> Result[ReadyReport, RunnerError]:
        """Wait for every node to become ready (NOS booted, accepting SSH/console)
        via the runner's `netlab initial --ready` — no config push. `templates` is
        the custom-config fileset the definition may reference (its readiness
        inventory is built with netlab create). Returns once ready, or a typed
        error if a node never came up."""
        try:
            resp = await self.client.post(
                f"{self.base_url}/ready",
                json={"definition": definition, "templates": templates},
                timeout=_READY_TIMEOUT_SECONDS,
            )
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"ready request failed: {exc}"))

        if resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            return Err(RunnerError("bad_definition", resp.text))
        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"ready failed: {resp.text}"))

        try:
            parsed = _ReadyResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected ready response: {exc}"))
        return Ok(ReadyReport(ready=parsed.ready))

    async def list_images(self) -> Result[frozenset[str], RunnerError]:
        """The repo:tag image names present on the host Docker daemon (delta 18:
        the catalog's image-presence source). The runner reports raw names;
        normalization and matching stay here in the backend."""
        try:
            resp = await self.client.get(f"{self.base_url}/images", timeout=_IMAGES_TIMEOUT_SECONDS)
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"images request failed: {exc}"))

        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"images rejected: {resp.text}"))

        try:
            parsed = _ImagesResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected images response: {exc}"))
        return Ok(frozenset(parsed.images))

    async def docker_usage(self) -> Result[DockerUsage, RunnerError]:
        """The Docker daemon's counts and disk footprint (delta 30). The runner
        is the only component with the socket, so this is the backend's only
        window onto what images and volumes are costing."""
        try:
            resp = await self.client.get(
                f"{self.base_url}/docker/usage", timeout=_DOCKER_USAGE_TIMEOUT_SECONDS
            )
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"docker usage request failed: {exc}"))

        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"docker usage rejected: {resp.text}"))

        try:
            parsed = _DockerUsageResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected docker usage response: {exc}"))

        return Ok(
            DockerUsage(
                root_dir=parsed.root_dir,
                containers_running=parsed.containers_running,
                containers_paused=parsed.containers_paused,
                containers_stopped=parsed.containers_stopped,
                containers_total=parsed.containers_total,
                images_total=parsed.images_total,
                disk=tuple(
                    DiskEntry(
                        kind=entry.kind,
                        total=entry.total,
                        active=entry.active,
                        size_bytes=entry.size_bytes,
                        reclaimable_bytes=entry.reclaimable_bytes,
                    )
                    for entry in parsed.disk
                ),
            )
        )

    async def container_stats(
        self, containers: tuple[str, ...]
    ) -> Result[dict[str, ContainerStats], RunnerError]:
        """Live cost of the named containers, keyed by container name. A name
        the daemon does not know is simply absent from the mapping.

        The runner caps a request at 64 containers, so a lab larger than that
        comes back as an error and its usage reads `live=false` — unmeasured
        rather than wrong. Chunking would only be worth it if labs that size
        turn up."""
        if not containers:
            return Ok({})
        try:
            resp = await self.client.get(
                f"{self.base_url}/docker/stats",
                params=[("container", name) for name in containers],
                timeout=_DOCKER_STATS_TIMEOUT_SECONDS,
            )
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"docker stats request failed: {exc}"))

        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"docker stats rejected: {resp.text}"))

        try:
            parsed = _StatsResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected docker stats response: {exc}"))

        return Ok(
            {
                entry.container: ContainerStats(
                    container=entry.container,
                    cpu_percent=entry.cpu_percent,
                    memory_bytes=entry.memory_bytes,
                    memory_limit_bytes=entry.memory_limit_bytes,
                    net_rx_bytes=entry.net_rx_bytes,
                    net_tx_bytes=entry.net_tx_bytes,
                    pids=entry.pids,
                )
                for entry in parsed.stats
            }
        )

    async def exec_command(
        self,
        definition: str,
        node: str,
        command: str,
        templates: dict[str, str],
        *,
        interactive: bool = False,
    ) -> Result[str, RunnerError]:
        """Run one operational command on a node via the runner's `netlab exec`
        (per-NOS transport). `definition` carries the stable `name:` so the runner
        can (re)build the matching inventory; `templates` is the custom-config
        fileset it references (the inventory's `netlab create` validates them).
        `interactive` asks for a persistent CLI channel where the node's
        transport is SSH (delta 17 — timed commands truncate on a one-shot exec
        channel); a no-op for docker-transport nodes. Returns the command's
        stdout."""
        try:
            resp = await self.client.post(
                f"{self.base_url}/exec",
                json={
                    "definition": definition,
                    "node": node,
                    "command": command,
                    "templates": templates,
                    "interactive": interactive,
                },
                timeout=_EXEC_TIMEOUT_SECONDS,
            )
        except httpx2.HTTPError as exc:
            return Err(RunnerError("transport", f"exec request failed: {exc}"))

        if resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            return Err(RunnerError("bad_definition", resp.text))
        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"exec rejected: {resp.text}"))

        try:
            parsed = _ExecResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected exec response: {exc}"))
        return Ok(parsed.stdout)
