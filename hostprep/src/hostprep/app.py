"""HTTP boundary for the host-preparation sidecar.

A tiny internal API the backend calls around deploy and destroy — the one
Twinlab component with the host network namespace and modprobe in reach
(NET_ADMIN + SYS_MODULE, /lib/modules read-only; no Docker socket, no netlab,
no definitions). Every request carries `X-Hostprep-Token` (shared secret the
compose stack requires) and is validated before any command runs: bridge
names against the exact shape netlab generates, modules against a fixed
allowlist.

Item outcomes are data, not HTTP errors: a request that executed returns 200
with per-item statuses (`not_bridge`, `in_use`, `error`, ...) and the backend
applies policy — the same philosophy as the runner's per-node config results.
"""

import asyncio
import hmac
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, StringConstraints, field_validator
from starlette.concurrency import run_in_threadpool

from hostprep import host

app = FastAPI(title="Twinlab hostprep", version="0.1.0")

_SYSFS_NET = Path("/sys/class/net")

# One mutation at a time: the primitives are check-then-act over shared host
# state, so two concurrent deploys could otherwise race `ip link add` on the
# same name. Operations are milliseconds; a queue is fine.
_ops_lock = asyncio.Lock()


def _authorize(x_hostprep_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("HOSTPREP_TOKEN")
    if not expected:
        # Fail closed: an unconfigured token must never mean open access.
        raise HTTPException(status_code=503, detail="HOSTPREP_TOKEN is not configured")
    if x_hostprep_token is None or not hmac.compare_digest(x_hostprep_token, expected):
        raise HTTPException(status_code=401, detail="invalid token")


type BridgeName = Annotated[str, StringConstraints(pattern=host.BRIDGE_NAME_PATTERN)]


class BridgeNames(BaseModel):
    # Bounded well above any real lab (netlab caps linkindex-derived names, and
    # a lab has at most a few LAN segments) — the cap only stops abuse.
    names: list[BridgeName] = Field(min_length=1, max_length=64)


class BridgeOutcomeModel(BaseModel):
    name: str
    status: host.BridgeStatus
    detail: str


class BridgesResponse(BaseModel):
    bridges: list[BridgeOutcomeModel]


class ModuleNames(BaseModel):
    names: list[str] = Field(min_length=1, max_length=16)

    @field_validator("names")
    @classmethod
    def _allowlisted(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - host.KERNEL_MODULES)
        if unknown:
            raise ValueError(f"not in the kernel-module allowlist: {', '.join(unknown)}")
        return value


class ModuleOutcomeModel(BaseModel):
    name: str
    ok: bool
    detail: str


class ModulesResponse(BaseModel):
    modules: list[ModuleOutcomeModel]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _bridge_response(outcomes: list[host.BridgeOutcome]) -> BridgesResponse:
    return BridgesResponse(
        bridges=[
            BridgeOutcomeModel(name=o.name, status=o.status, detail=o.detail) for o in outcomes
        ]
    )


@app.put("/bridges", dependencies=[Depends(_authorize)])
async def ensure_bridges(request: BridgeNames) -> BridgesResponse:
    def work() -> list[host.BridgeOutcome]:
        return [
            host.ensure_bridge(name, sysfs_net=_SYSFS_NET, run=host.run_command)
            for name in request.names
        ]

    async with _ops_lock:
        # Subprocess work stays off the event loop.
        return _bridge_response(await run_in_threadpool(work))


@app.delete("/bridges", dependencies=[Depends(_authorize)])
async def delete_bridges(request: BridgeNames) -> BridgesResponse:
    def work() -> list[host.BridgeOutcome]:
        return [
            host.delete_bridge(name, sysfs_net=_SYSFS_NET, run=host.run_command)
            for name in request.names
        ]

    async with _ops_lock:
        return _bridge_response(await run_in_threadpool(work))


@app.post("/modules", dependencies=[Depends(_authorize)])
async def load_modules(request: ModuleNames) -> ModulesResponse:
    def work() -> list[host.ModuleOutcome]:
        return [host.load_module(name, run=host.run_command) for name in request.names]

    async with _ops_lock:
        outcomes = await run_in_threadpool(work)
    return ModulesResponse(
        modules=[ModuleOutcomeModel(name=o.name, ok=o.ok, detail=o.detail) for o in outcomes]
    )
