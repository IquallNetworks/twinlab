"""Server-Sent Events: relay clab-api lab events to the browser.

clab-api streams container lifecycle events as NDJSON on a long-lived connection.
We distill each to a lean `{lab, node, action, timestamp}` and re-emit it as SSE so
the frontend can invalidate the affected lab's queries instead of polling. One
upstream clab-api stream per browser connection (simple; the tool is low-scale).

Auth is resolved up front and its DB session released before the stream begins —
a long-lived SSE connection must not pin a DB connection for its whole lifetime
(which the usual request-scoped `require` dependency would do).
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.service import effective_permissions
from twinlab_backend.auth.sessions import resolve_session
from twinlab_backend.config import Settings
from twinlab_backend.deps import ClabClientDep, SettingsDep
from twinlab_backend.models import LabEvent
from twinlab_backend.result import Err
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.clab_api import LabEvent as ClabLabEvent

router = APIRouter(tags=["events"])

# Emit an SSE comment this often while idle so intermediaries keep the connection
# open and a dropped upstream is noticed promptly.
_KEEPALIVE_SECONDS = 15.0


async def _authorize(request: Request, settings: Settings) -> None:
    """Check the session cookie grants `lab:read`, using a short-lived session that
    is closed before streaming begins."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    async with request.app.state.session_factory() as session:
        resolved = await resolve_session(session, token)
        if isinstance(resolved, Err):
            raise HTTPException(status_code=401, detail="invalid or expired session")
        if perms.LAB_READ not in effective_permissions(resolved.value):
            raise HTTPException(status_code=403, detail=f"missing permission: {perms.LAB_READ}")


async def _sse(clab: ClabApiClient) -> AsyncIterator[str]:
    """Relay upstream events as SSE, interleaving keepalive comments while idle.
    A background task feeds a queue so we can time out on it for the keepalive; on
    client disconnect the generator is closed and the producer cancelled."""
    queue: asyncio.Queue[ClabLabEvent | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in clab.stream_events():
                await queue.put(event)
        finally:
            await queue.put(None)  # sentinel: upstream ended

    task = asyncio.create_task(produce())
    try:
        yield ": connected\n\n"  # flush headers so EventSource fires `open`
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event is None:
                break
            payload = LabEvent(
                lab=event.lab, node=event.node, action=event.action, timestamp=event.timestamp
            )
            yield f"data: {payload.model_dump_json()}\n\n"
    finally:
        _ = task.cancel()


@router.get("/events")
async def lab_events(
    request: Request, clab: ClabClientDep, settings: SettingsDep
) -> StreamingResponse:
    await _authorize(request, settings)
    return StreamingResponse(
        _sse(clab),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering (nginx) so events flush immediately.
            "X-Accel-Buffering": "no",
        },
    )
