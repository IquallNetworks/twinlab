"""Server-Sent Events: relay clab-api lab events to the browser.

clab-api streams container lifecycle events as NDJSON on a long-lived connection.
We distill each to a lean `{lab, node, action, timestamp}` and re-emit it as SSE so
the frontend can invalidate the affected lab's queries instead of polling. One
upstream clab-api stream per browser connection (simple; the tool is low-scale).

Events are filtered to the labs the caller may read: a global `lab:read` sees all;
otherwise only owned labs and labs granted to the caller (directly or via a group).
The readable set is resolved at connect and re-resolved on a TTL, since a grant can
change during a long-lived stream. Auth is resolved up front and its DB session
released before streaming — a long-lived SSE connection must not pin a DB connection.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from twinlab_backend.auth.service import readable_lab_names
from twinlab_backend.auth.sessions import resolve_session
from twinlab_backend.config import Settings
from twinlab_backend.db.models import User
from twinlab_backend.deps import ClabClientDep, SettingsDep
from twinlab_backend.models import LabEvent
from twinlab_backend.result import Err
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.clab_api import LabEvent as ClabLabEvent

router = APIRouter(tags=["events"])

# Emit an SSE comment this often while idle so intermediaries keep the connection
# open and a dropped upstream is noticed promptly.
_KEEPALIVE_SECONDS = 15.0
# Re-resolve the caller's readable-lab set no more often than this; a grant made
# mid-stream takes effect within the window (open item in docs/rbac-v2.md).
_READABLE_TTL_SECONDS = 30.0


async def _authenticate(request: Request, settings: Settings) -> User:
    """Resolve the session cookie in a short-lived DB session and return the user.
    Any authenticated user may open the stream; events are filtered per lab."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    async with request.app.state.session_factory() as session:
        resolved = await resolve_session(session, token)
        if isinstance(resolved, Err):
            raise HTTPException(status_code=401, detail="invalid or expired session")
        return resolved.value


async def _resolve_readable(request: Request, user: User) -> set[str] | None:
    async with request.app.state.session_factory() as session:
        return await readable_lab_names(session, user)


async def _sse(request: Request, clab: ClabApiClient, user: User) -> AsyncIterator[str]:
    """Relay upstream events as SSE, dropping events for labs the caller can't read
    and interleaving keepalive comments while idle. A background task feeds a queue so
    we can time out on it for both the keepalive and the readable-set refresh."""
    queue: asyncio.Queue[ClabLabEvent | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in clab.stream_events():
                await queue.put(event)
        finally:
            await queue.put(None)  # sentinel: upstream ended

    task = asyncio.create_task(produce())
    readable = await _resolve_readable(request, user)
    next_refresh = asyncio.get_event_loop().time() + _READABLE_TTL_SECONDS
    try:
        yield ": connected\n\n"  # flush headers so EventSource fires `open`
        while True:
            if asyncio.get_event_loop().time() >= next_refresh:
                readable = await _resolve_readable(request, user)
                next_refresh = asyncio.get_event_loop().time() + _READABLE_TTL_SECONDS
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event is None:
                break
            # readable is None => global reader (see everything); else a name set.
            if readable is not None and event.lab not in readable:
                continue
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
    user = await _authenticate(request, settings)
    return StreamingResponse(
        _sse(request, clab, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering (nginx) so events flush immediately.
            "X-Accel-Buffering": "no",
        },
    )
