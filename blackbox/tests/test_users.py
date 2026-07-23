"""User management contract (global user:manage)."""

import contextlib
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient, UserSummary

from _config import DEFAULT_PASSWORD, SuiteConfig, UserClientFactory


@pytest.fixture
async def user(admin: TwinlabClient, unique: Callable[[str], str]) -> AsyncIterator[UserSummary]:
    """A freshly created user, best-effort deleted afterwards."""
    created = await admin.create_user(unique("user"), DEFAULT_PASSWORD)
    yield created
    with contextlib.suppress(TwinlabApiError):
        await admin.delete_user(created.id)


async def test_create_user_defaults(user: UserSummary) -> None:
    assert user.is_active is True
    # No roles requested -> the baseline "user" role (authenticated, no access).
    assert user.roles == {"user"}


async def test_created_user_appears_in_list(admin: TwinlabClient, user: UserSummary) -> None:
    listed = {entry.id: entry for entry in await admin.list_users()}
    assert listed[user.id] == user


async def test_created_user_can_login(
    config: SuiteConfig, user: UserSummary, anon: TwinlabClient
) -> None:
    info = await anon.login(user.username, DEFAULT_PASSWORD)
    assert info.username == user.username
    assert info.roles == {"user"}


async def test_duplicate_username_is_409(admin: TwinlabClient, user: UserSummary) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_user(user.username, DEFAULT_PASSWORD)
    assert excinfo.value.status_code == 409


async def test_short_password_is_422(admin: TwinlabClient, unique: Callable[[str], str]) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_user(unique("user"), "short")
    assert excinfo.value.status_code == 422


async def test_set_roles_full_replace(admin: TwinlabClient, user: UserSummary) -> None:
    granted = await admin.set_user_roles(user.id, {"global_viewer"})
    assert granted.roles == {"global_viewer"}

    cleared = await admin.set_user_roles(user.id, set())
    assert cleared.roles == set()


async def test_set_unknown_role_is_422(admin: TwinlabClient, user: UserSummary) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.set_user_roles(user.id, {"bb-no-such-role"})
    assert excinfo.value.status_code == 422


async def test_users_endpoints_require_user_manage(
    anon: TwinlabClient, config: SuiteConfig, user: UserSummary
) -> None:
    # A fresh default user holds no user:manage.
    _ = await anon.login(user.username, DEFAULT_PASSWORD)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await anon.list_users()
    assert excinfo.value.status_code == 403


async def test_get_user_matches_list(admin: TwinlabClient, user: UserSummary) -> None:
    assert await admin.get_user(user.id) == user


async def test_get_unknown_user_is_404(admin: TwinlabClient) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.get_user(uuid.uuid4())
    assert excinfo.value.status_code == 404


async def test_delete_user(
    admin: TwinlabClient, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    created = await admin.create_user(unique("user"), DEFAULT_PASSWORD)
    await admin.delete_user(created.id)
    assert created.id not in {entry.id for entry in await admin.list_users()}
    async with TwinlabClient(config.base_url) as fresh:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await fresh.login(created.username, DEFAULT_PASSWORD)
        assert excinfo.value.status_code == 401


async def test_admin_password_reset_revokes_all_sessions(
    admin: TwinlabClient, config: SuiteConfig, make_user_client: UserClientFactory
) -> None:
    summary, client = await make_user_client(None)
    await admin.set_user_password(summary.id, "bb-password-2")

    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.me()
    assert excinfo.value.status_code == 401

    async with TwinlabClient(config.base_url) as fresh:
        with pytest.raises(TwinlabApiError) as rejected:
            _ = await fresh.login(summary.username, DEFAULT_PASSWORD)
        assert rejected.value.status_code == 401
        info = await fresh.login(summary.username, "bb-password-2")
        assert info.username == summary.username


async def test_deactivate_revokes_and_blocks_login_reactivate_restores(
    admin: TwinlabClient, config: SuiteConfig, make_user_client: UserClientFactory
) -> None:
    summary, client = await make_user_client(None)

    deactivated = await admin.set_user_active(summary.id, False)
    assert deactivated.is_active is False
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.me()
    assert excinfo.value.status_code == 401
    async with TwinlabClient(config.base_url) as fresh:
        with pytest.raises(TwinlabApiError) as rejected:
            _ = await fresh.login(summary.username, DEFAULT_PASSWORD)
        assert rejected.value.status_code == 401

    reactivated = await admin.set_user_active(summary.id, True)
    assert reactivated.is_active is True
    async with TwinlabClient(config.base_url) as fresh:
        info = await fresh.login(summary.username, DEFAULT_PASSWORD)
        assert info.username == summary.username


async def test_last_active_admin_cannot_be_removed(admin: TwinlabClient) -> None:
    # The rule guards the LAST active admin, so it is only testable when
    # exactly one exists (deactivating a non-last admin would succeed — and
    # kill the bootstrap account). `roles` covers direct bindings only; a
    # group-derived admin would make this conservative, which is fine.
    active_admins = [
        entry for entry in await admin.list_users() if entry.is_active and "admin" in entry.roles
    ]
    if len(active_admins) != 1:
        pytest.skip(f"{len(active_admins)} active admins present; the rule needs exactly one")
    last = active_admins[0]

    with pytest.raises(TwinlabApiError) as deactivate:
        _ = await admin.set_user_active(last.id, False)
    assert deactivate.value.status_code == 409

    with pytest.raises(TwinlabApiError) as delete:
        await admin.delete_user(last.id)
    assert delete.value.status_code == 409
