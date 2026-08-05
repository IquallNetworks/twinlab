"""Client for the netlab-runner sidecar.

The runner owns config push: `POST /configure {definition}` runs `netlab create`
+ `netlab initial` (Ansible over the docker connection) and returns per-node
results. The definition must carry a stable `name:` so the runner's regenerated
inventory targets the containers clab-api deployed.

httpx is a third-party boundary: its exceptions and the runner's JSON are
translated here into typed results; nothing propagates as an exception.
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

import httpx
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
class ReadyReport:
    ready: bool


class _ReadyResponse(BaseModel):
    ready: bool


@dataclass(frozen=True, slots=True)
class RunnerClient:
    client: httpx.AsyncClient
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
        except httpx.HTTPError as exc:
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
        except httpx.HTTPError as exc:
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
        except httpx.HTTPError as exc:
            return Err(RunnerError("transport", f"images request failed: {exc}"))

        if resp.status_code != HTTPStatus.OK:
            return Err(RunnerError("runner", f"images rejected: {resp.text}"))

        try:
            parsed = _ImagesResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(RunnerError("runner", f"unexpected images response: {exc}"))
        return Ok(frozenset(parsed.images))

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
        except httpx.HTTPError as exc:
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
