"""FastAPI application factory.

Settings and the shared httpx client / clab-api client are built once in the
lifespan and stashed on `app.state`; handlers reach them via the typed
dependencies in `deps`.
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from twinlab_backend.api.auth import router as auth_router
from twinlab_backend.api.health import router as health_router
from twinlab_backend.api.labs import router as labs_router
from twinlab_backend.api.users import router as users_router
from twinlab_backend.auth.bootstrap import ensure_admin, seed_rbac
from twinlab_backend.config import load_settings
from twinlab_backend.db.base import create_engine, make_session_factory
from twinlab_backend.result import Err
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.runner_client import RunnerClient

_HTTP_TIMEOUT_SECONDS = 30.0
_API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    loaded = load_settings(os.environ)
    # Startup boundary: without valid config the app cannot serve, so fail fast.
    if isinstance(loaded, Err):
        raise RuntimeError(loaded.error.message)
    settings = loaded.value

    engine = create_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    # Keep RBAC in sync with the code-defined roles/permissions and guarantee an
    # admin exists. Migrations have already run (container entrypoint).
    async with session_factory() as session:
        await seed_rbac(session)
        await ensure_admin(
            session,
            settings.bootstrap_admin_username,
            settings.bootstrap_admin_password.get_secret_value(),
        )

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        app.state.settings = settings
        app.state.session_factory = session_factory
        app.state.clab_client = ClabApiClient(
            client=client,
            base_url=settings.clab_api_url,
            username=settings.clab_api_username,
            password=settings.clab_api_password.get_secret_value(),
        )
        app.state.runner_client = RunnerClient(
            client=client,
            base_url=settings.netlab_runner_url,
        )
        try:
            yield
        finally:
            await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Twinlab backend", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router, prefix=_API_PREFIX)
    app.include_router(auth_router, prefix=_API_PREFIX)
    app.include_router(labs_router, prefix=_API_PREFIX)
    app.include_router(users_router, prefix=_API_PREFIX)
    return app


app = create_app()
