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

import httpx
from pydantic import BaseModel, ValidationError

from twinlab_backend.result import Err, Ok, Result

# netlab create + Ansible push blocks until every node is configured; for several
# nodes this runs into minutes, well past the client default.
_CONFIGURE_TIMEOUT_SECONDS = 600.0


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
    def status(self) -> str:
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


@dataclass(frozen=True, slots=True)
class RunnerClient:
    client: httpx.AsyncClient
    base_url: str

    async def configure(self, definition: str) -> Result[ConfigureReport, RunnerError]:
        try:
            resp = await self.client.post(
                f"{self.base_url}/configure",
                json={"definition": definition},
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
