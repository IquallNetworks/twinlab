"""Suite plumbing: env-only config, a session ready-gate, and client fixtures.

All configuration is required — a missing variable aborts the run (never a
silent skip that reads as green).
"""

import asyncio
import contextlib
import os
import secrets
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from twinlab_client import GroupSummary, LabDetail, TwinlabApiError, TwinlabClient, UserSummary

from _config import (
    DEFAULT_PASSWORD,
    GroupFactory,
    LabFactory,
    SuiteConfig,
    UserClientFactory,
)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.exit(f"required environment variable {name} is not set (see blackbox/README.md)", 4)
    return value


@pytest.fixture(scope="session")
def config() -> SuiteConfig:
    return SuiteConfig(
        base_url=_required_env("TWINLAB_URL"),
        admin_username=_required_env("TWINLAB_ADMIN_USERNAME"),
        admin_password=_required_env("TWINLAB_ADMIN_PASSWORD"),
    )


@pytest.fixture(scope="session", autouse=True)
def backend_ready(config: SuiteConfig) -> None:
    """Abort the whole run unless GET /health/ready reports "ready".

    Sync on purpose: it runs once in its own event loop, independent of the
    per-test loops pytest-asyncio creates.
    """

    async def check() -> None:
        async with TwinlabClient(config.base_url) as client:
            readiness = await client.ready()
            if readiness.status != "ready":
                pytest.exit(f"backend at {config.base_url} is degraded: {readiness.checks}", 4)

    try:
        asyncio.run(check())
    except httpx.HTTPError as exc:
        pytest.exit(f"backend at {config.base_url} is unreachable: {exc}", 4)


@pytest.fixture
async def anon(config: SuiteConfig) -> AsyncIterator[TwinlabClient]:
    """An unauthenticated client."""
    async with TwinlabClient(config.base_url) as client:
        yield client


@pytest.fixture
async def admin(config: SuiteConfig) -> AsyncIterator[TwinlabClient]:
    """A client logged in as the bootstrap admin. Logged out at teardown so
    session rows don't accumulate on the persistent DB."""
    async with TwinlabClient(config.base_url) as client:
        _ = await client.login(config.admin_username, config.admin_password)
        yield client
        with contextlib.suppress(TwinlabApiError, httpx.HTTPError):
            await client.logout()


@pytest.fixture
def unique() -> Callable[[str], str]:
    """Collision-free resource names: unique('user') -> 'bb-user-3f9a2c1d'."""

    def make(prefix: str) -> str:
        return f"bb-{prefix}-{secrets.token_hex(4)}"

    return make


@pytest.fixture
async def make_user_client(
    admin: TwinlabClient, config: SuiteConfig, unique: Callable[[str], str]
) -> AsyncIterator[UserClientFactory]:
    """Create a user with the given global roles (None = server default) and a
    client logged in as them. Teardown closes the clients and best-effort
    deletes the users."""
    made: list[tuple[UserSummary, TwinlabClient]] = []

    async def factory(roles: set[str] | None) -> tuple[UserSummary, TwinlabClient]:
        summary = await admin.create_user(unique("user"), DEFAULT_PASSWORD, roles)
        client = TwinlabClient(config.base_url)
        _ = await client.login(summary.username, DEFAULT_PASSWORD)
        made.append((summary, client))
        return summary, client

    yield factory
    for summary, client in made:
        with contextlib.suppress(TwinlabApiError, httpx.HTTPError):
            await client.logout()
        await client.aclose()
        with contextlib.suppress(TwinlabApiError):
            await admin.delete_user(summary.id)


@pytest.fixture
async def make_lab(admin: TwinlabClient, unique: Callable[[str], str]) -> AsyncIterator[LabFactory]:
    """Create a lab record owned by the given client (None = the admin).
    Teardown best-effort destroys-with-remove as the admin — submitting the
    destroy job and waiting for it, so the next test can't race a teardown
    still running server-side."""
    names: list[str] = []

    async def factory(owner: TwinlabClient | None) -> LabDetail:
        creator = owner if owner is not None else admin
        detail = await creator.create_lab(unique("lab"))
        names.append(detail.name)
        return detail

    yield factory
    for name in names:
        with contextlib.suppress(TwinlabApiError, TimeoutError):
            job = await admin.destroy_lab(name, remove=True)
            _ = await admin.wait_job(name, job.id, timeout=120)


@pytest.fixture
async def make_group(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> AsyncIterator[GroupFactory]:
    """Create a group; teardown best-effort deletes it."""
    ids: list[GroupSummary] = []

    async def factory() -> GroupSummary:
        group = await admin.create_group(unique("group"), "black-box test group")
        ids.append(group)
        return group

    yield factory
    for group in ids:
        with contextlib.suppress(TwinlabApiError):
            await admin.delete_group(group.id)
