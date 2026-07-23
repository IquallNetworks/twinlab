"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from twinlab_backend.deps import ClabClientDep, SessionDep
from twinlab_backend.result import Ok
from twinlab_backend.services.db import ping

router = APIRouter(prefix="/health", tags=["health"])


class Liveness(BaseModel):
    status: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("")
async def liveness() -> Liveness:
    """Process is up. Deliberately dependency-free so it never flaps on a
    downstream outage."""
    return Liveness(status="ok")


@router.get("/ready")
async def readiness(
    response: Response,
    session: SessionDep,
    clab: ClabClientDep,
) -> Readiness:
    """Report reachability of the dependencies needed to serve real work."""
    db = await ping(session)
    clab_health = await clab.health()

    checks = {
        "database": "ok" if isinstance(db, Ok) else db.error.message,
        "clab_api": "ok" if isinstance(clab_health, Ok) else clab_health.error.message,
    }
    ready = all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = 503
    return Readiness(status="ready" if ready else "degraded", checks=checks)
