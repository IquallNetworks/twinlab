"""FastAPI dependency wiring.

The settings and clab-api client are built once in the app lifespan and stashed
on `app.state`; these accessors hand them to route handlers as typed
dependencies.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.config import Settings
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.custom_config import BuiltinLibrary
from twinlab_backend.services.runner_client import RunnerClient


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_builtin_library(request: Request) -> BuiltinLibrary:
    return request.app.state.builtin_library


def get_clab_client(request: Request) -> ClabApiClient:
    return request.app.state.clab_client


def get_runner_client(request: Request) -> RunnerClient:
    return request.app.state.runner_client


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session; it is closed when the request ends."""
    async with request.app.state.session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
BuiltinLibraryDep = Annotated[BuiltinLibrary, Depends(get_builtin_library)]
ClabClientDep = Annotated[ClabApiClient, Depends(get_clab_client)]
RunnerClientDep = Annotated[RunnerClient, Depends(get_runner_client)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]
