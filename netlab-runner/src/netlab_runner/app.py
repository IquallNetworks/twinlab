"""HTTP boundary for the netlab config-push runner.

A thin internal API the backend calls (like it calls clab-api). `POST /configure`
renders and pushes a lab's config and returns structured per-node results. A bad
definition is a 422; a failed push still returns 200 with `succeeded: false` and
the per-node breakdown, so the backend decides how to surface it.
"""

import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from netlab_runner.runner import (
    ConfigureOutcome,
    ExecOutcome,
    ReadyOutcome,
    configure,
    exec_command,
    wait_ready,
)

app = FastAPI(title="Twinlab netlab-runner", version="0.1.0")

# netlab keeps global state under ~/.netlab (a status dir, a defaults cache) that
# two concurrent `netlab create`/`initial`/`exec` runs would race on. HOME can't be
# isolated per call here — netlab's Ansible needs the real ~/.ansible — so serialize
# every netlab subprocess (config push and validation exec) through one lock: one
# at a time. Deploys (clab-api's job) stay concurrent; only these netlab steps are
# single-file.
_netlab_lock = asyncio.Lock()


class ConfigureRequest(BaseModel):
    # A netlab definition (YAML) carrying a stable `name:` so the regenerated
    # inventory targets the deployed containers.
    definition: str = Field(min_length=1)
    # Custom-config templates keyed by relative path (e.g. `mpls_te/ios.j2`),
    # written into the workdir so `netlab initial` can render whichever the
    # definition's `config:` attribute references. Default empty: most labs use
    # no custom config. The backend owns the fileset (built-in + user templates).
    templates: dict[str, str] = Field(default_factory=dict)


class NodeResultModel(BaseModel):
    node: str
    ok: int
    changed: int
    unreachable: int
    failed: int


class ConfigureResponse(BaseModel):
    lab_name: str
    succeeded: bool
    nodes: list[NodeResultModel]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class ExecRequest(BaseModel):
    # A netlab definition (YAML) with a stable `name:`, the short node name, and
    # the operational command to run. netlab picks the per-NOS transport.
    definition: str = Field(min_length=1)
    node: str = Field(min_length=1)
    command: str = Field(min_length=1)
    # Custom-config templates the definition may reference — needed because the
    # exec inventory is built with `netlab create`, which validates that every
    # `config:` template exists. Empty for a definition with no custom config.
    templates: dict[str, str] = Field(default_factory=dict)


class ExecResponse(BaseModel):
    node: str
    stdout: str


@app.post("/exec")
async def exec_endpoint(request: ExecRequest) -> ExecResponse:
    # `netlab exec` is blocking subprocess work; keep it off the loop and serialize
    # it (a cache-miss runs `netlab create`, which races on ~/.netlab).
    async with _netlab_lock:
        outcome = await run_in_threadpool(
            exec_command, request.definition, request.node, request.command, request.templates
        )
    if isinstance(outcome, ExecOutcome):
        return ExecResponse(node=outcome.node, stdout=outcome.stdout)
    status = 422 if outcome.stage == "netlab-create" else 500
    raise HTTPException(
        status_code=status,
        detail={
            "stage": outcome.stage,
            "message": outcome.message,
            "output": outcome.output[-2000:],
        },
    )


class ReadyRequest(BaseModel):
    # A netlab definition (YAML) with a stable `name:`, plus the custom-config
    # templates its `config:` may reference (the readiness inventory is built with
    # netlab create, which validates them).
    definition: str = Field(min_length=1)
    templates: dict[str, str] = Field(default_factory=dict)


class ReadyResponse(BaseModel):
    ready: bool


@app.post("/ready")
async def ready_endpoint(request: ReadyRequest) -> ReadyResponse:
    # Readiness polls SSH/console per node; keep it off the loop and serialized (a
    # cache-miss runs `netlab create`, which races on ~/.netlab).
    async with _netlab_lock:
        outcome = await run_in_threadpool(wait_ready, request.definition, request.templates)
    if isinstance(outcome, ReadyOutcome):
        return ReadyResponse(ready=outcome.ready)
    # netlab-create = bad definition (422); netlab-ready = nodes never came up (504,
    # a timeout upstream); anything else is an internal fault (500).
    status = (
        422 if outcome.stage == "netlab-create" else 504 if outcome.stage == "netlab-ready" else 500
    )
    raise HTTPException(
        status_code=status,
        detail={
            "stage": outcome.stage,
            "message": outcome.message,
            "output": outcome.output[-2000:],
        },
    )


@app.post("/configure")
async def configure_endpoint(request: ConfigureRequest) -> ConfigureResponse:
    # netlab create + initial is blocking subprocess work; keep it off the loop.
    # Serialized so concurrent pushes don't race on netlab's shared ~/.netlab.
    async with _netlab_lock:
        outcome = await run_in_threadpool(configure, request.definition, request.templates)
    if isinstance(outcome, ConfigureOutcome):
        return ConfigureResponse(
            lab_name=outcome.lab_name,
            succeeded=outcome.succeeded,
            nodes=[
                NodeResultModel(
                    node=n.node,
                    ok=n.ok,
                    changed=n.changed,
                    unreachable=n.unreachable,
                    failed=n.failed,
                )
                for n in outcome.nodes
            ],
        )

    status = 422 if outcome.stage == "netlab-create" else 500
    raise HTTPException(
        status_code=status,
        detail={
            "stage": outcome.stage,
            "message": outcome.message,
            "output": outcome.output[-2000:],
        },
    )
