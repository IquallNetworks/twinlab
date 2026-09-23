import httpx2

from twinlab_backend.app import create_app


async def test_liveness_is_dependency_free() -> None:
    # Liveness reads no app.state, so we can exercise it without the lifespan —
    # and httpx2's AsyncClient is fully typed (unlike starlette's TestClient).
    transport = httpx2.ASGITransport(app=create_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
