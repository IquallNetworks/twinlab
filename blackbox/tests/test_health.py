"""Health endpoints (unauthenticated)."""

from twinlab_client import TwinlabClient


async def test_health_is_ok(anon: TwinlabClient) -> None:
    liveness = await anon.health()
    assert liveness.status == "ok"


async def test_ready_reports_every_check_ok(anon: TwinlabClient) -> None:
    # The session gate already required status="ready"; pin the shape too:
    # ready means every individual check reads "ok".
    readiness = await anon.ready()
    assert readiness.status == "ready"
    assert readiness.checks, "readiness must enumerate its dependency checks"
    assert all(value == "ok" for value in readiness.checks.values())
