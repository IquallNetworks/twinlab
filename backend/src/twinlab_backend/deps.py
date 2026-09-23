"""FastAPI dependency wiring.

The settings and clab-api client are built once in the app lifespan and stashed
on `app.state`; these accessors hand them to route handlers as typed
dependencies.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twinlab_backend.auth.oidc.metadata import OidcCache
from twinlab_backend.config import Settings
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.custom_config import BuiltinLibrary
from twinlab_backend.services.host_metrics import HostSnapshot
from twinlab_backend.services.host_prep import HostPrepClient
from twinlab_backend.services.network_templates import NetworkTemplateLibrary
from twinlab_backend.services.runner_client import RunnerClient


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_oidc_cache(request: Request) -> OidcCache:
    return request.app.state.oidc_cache


def get_hostprep_client(request: Request) -> HostPrepClient | None:
    """None when the sidecar isn't configured — the backend runs without it and
    only a deploy that needs host preparation fails, with a clear job error."""
    return request.app.state.hostprep_client


def get_builtin_library(request: Request) -> BuiltinLibrary:
    return request.app.state.builtin_library


def get_network_templates(request: Request) -> NetworkTemplateLibrary:
    return request.app.state.network_templates


def get_host_snapshot(request: Request) -> HostSnapshot | None:
    """The most recent host reading (delta 30). None only if no sample has ever
    succeeded — the lifespan primes one before the app serves."""
    return request.app.state.host_snapshot


def get_clab_client(request: Request) -> ClabApiClient:
    return request.app.state.clab_client


def get_runner_client(request: Request) -> RunnerClient:
    return request.app.state.runner_client


@asynccontextmanager
async def shielded_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """A pooled session whose close SURVIVES task cancellation.

    A client disconnect cancels the serving task, and with a plain
    `async with`, the CancelledError interrupts `session.close()` itself — the
    pooled connection is never checked back in. Enough of those (browsers and
    tests abandon in-flight requests constantly) exhausts the pool, and every
    later request blocks on checkout: observed live 2026-08-07 as SQLAlchemy's
    "non-checked-in connection" GC warning followed by the frontend blanking
    behind the auth gate — first on plain routes, then (after get_db was
    fixed) once more in the SSE handshake. shield() lets the close run to
    completion in its own task while the cancelled caller unwinds. Use this
    for EVERY session opened in a client-cancellable path.

    A rare residual warning (~once per full e2e run) can still surface from
    SQLAlchemy's OWN terminate path — connectors/asyncio.py already shields
    `_terminate_graceful_close()` and the greenlet bridge re-raises the
    pending cancellation through it anyway. That is upstream behavior, not a
    seam here; the GC terminate is the designed backstop (pool slot
    reclaimed, no exhaustion). Don't chase it unless the per-run count
    grows."""
    session = factory()
    try:
        yield session
    finally:
        await asyncio.shield(session.close())


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session; it is closed (shielded — see
    `shielded_session`) when the request ends."""
    async with shielded_session(request.app.state.session_factory) as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
OidcCacheDep = Annotated[OidcCache, Depends(get_oidc_cache)]
BuiltinLibraryDep = Annotated[BuiltinLibrary, Depends(get_builtin_library)]
NetworkTemplatesDep = Annotated[NetworkTemplateLibrary, Depends(get_network_templates)]
ClabClientDep = Annotated[ClabApiClient, Depends(get_clab_client)]
HostSnapshotDep = Annotated[HostSnapshot | None, Depends(get_host_snapshot)]
RunnerClientDep = Annotated[RunnerClient, Depends(get_runner_client)]
HostPrepDep = Annotated[HostPrepClient | None, Depends(get_hostprep_client)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]
