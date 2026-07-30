"""In-process fan-out of job lifecycle events to the open SSE streams
(contract delta 16).

Container events are RELAYED from clab-api, so every stream can just open its
own upstream connection. Job events have no upstream — they are born here, in
the job runner — so they need a process-local bus. That rests on the same
single-process assumption as the job tasks themselves and the orphan sweeps.

The bus is deliberately LOSSY: `publish` never blocks and never raises, so a
subscriber that stopped reading cannot stall the job it is watching. The
stream has no replay by contract, so consumers already tolerate a gap.
"""

import asyncio
from collections.abc import Generator
from contextlib import contextmanager

from twinlab_backend.models import JobEvent

# Per-subscriber buffer. Job events arrive at most a handful per operation, so
# a stream this far behind is not reading at all.
_QUEUE_SIZE = 64


class JobEventBroker:
    """Fan job events out to every open stream. One instance per app, built in
    the lifespan and reached through `app.state.job_events`."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[JobEvent]] = set()

    @contextmanager
    def subscribe(self) -> Generator[asyncio.Queue[JobEvent]]:
        """A queue of events for one stream, unsubscribed on exit — the
        context manager is what guarantees an abandoned stream's queue stops
        being written to."""
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, event: JobEvent) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Boundary adapter: asyncio signals a full queue by raising.
                # Dropping beats blocking the job runner on a dead reader.
                continue
