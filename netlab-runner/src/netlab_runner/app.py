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

from netlab_runner.runner import ConfigureOutcome, configure

app = FastAPI(title="Twinlab netlab-runner", version="0.1.0")

# netlab keeps global state under ~/.netlab (a status dir, a defaults cache) that
# two concurrent `netlab create`/`initial` runs would race on. HOME can't be
# isolated per call here — netlab initial's Ansible needs the real ~/.ansible — so
# serialize config pushes instead: one lab configures at a time. Deploys stay
# concurrent; only this push step is single-file.
_configure_lock = asyncio.Lock()


class ConfigureRequest(BaseModel):
    # A netlab definition (YAML) carrying a stable `name:` so the regenerated
    # inventory targets the deployed containers.
    definition: str = Field(min_length=1)


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


@app.post("/configure")
async def configure_endpoint(request: ConfigureRequest) -> ConfigureResponse:
    # netlab create + initial is blocking subprocess work; keep it off the loop.
    # Serialized so concurrent pushes don't race on netlab's shared ~/.netlab.
    async with _configure_lock:
        outcome = await run_in_threadpool(configure, request.definition)
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
