"""Auth contract: login/logout/me, the opaque-credential rule, password change."""

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import ALTERNATE_PASSWORD, DEFAULT_PASSWORD, SuiteConfig, UserClientFactory


async def test_me_unauthenticated_is_401(anon: TwinlabClient) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await anon.me()
    assert excinfo.value.status_code == 401


async def test_login_wrong_password_is_opaque_401(anon: TwinlabClient, config: SuiteConfig) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await anon.login(config.admin_username, "definitely-not-the-password")
    assert excinfo.value.status_code == 401
    assert excinfo.value.message == "invalid credentials"


async def test_login_unknown_user_is_same_401(anon: TwinlabClient) -> None:
    # Deliberately opaque: unknown-user and wrong-password are indistinguishable.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await anon.login("bb-no-such-user", "definitely-not-the-password")
    assert excinfo.value.status_code == 401
    assert excinfo.value.message == "invalid credentials"


async def test_login_me_logout_roundtrip(anon: TwinlabClient, config: SuiteConfig) -> None:
    info = await anon.login(config.admin_username, config.admin_password)
    assert info.username == config.admin_username
    assert "admin" in info.roles

    me = await anon.me()
    assert me == info

    await anon.logout()
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await anon.me()
    assert excinfo.value.status_code == 401


async def test_logout_is_idempotent(anon: TwinlabClient) -> None:
    # 204 even without a session.
    await anon.logout()
    await anon.logout()


async def test_change_password_requires_current(
    config: SuiteConfig, make_user_client: UserClientFactory
) -> None:
    summary, client = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        await client.change_password("not-the-current-password", ALTERNATE_PASSWORD)
    assert excinfo.value.status_code in (401, 403)

    # The rejected change must not have altered the password: the attempted
    # new password does not log in, the current one still does.
    async with TwinlabClient(config.base_url) as fresh:
        with pytest.raises(TwinlabApiError) as rejected:
            _ = await fresh.login(summary.username, ALTERNATE_PASSWORD)
        assert rejected.value.status_code == 401
        info = await fresh.login(summary.username, DEFAULT_PASSWORD)
        assert info.username == summary.username


async def test_change_password_keeps_this_session_revokes_others(
    config: SuiteConfig, make_user_client: UserClientFactory
) -> None:
    summary, first = await make_user_client(None)
    async with TwinlabClient(config.base_url) as second:
        _ = await second.login(summary.username, DEFAULT_PASSWORD)

        await first.change_password(DEFAULT_PASSWORD, ALTERNATE_PASSWORD)

        # The changing session survives; the other one is revoked.
        me = await first.me()
        assert me.username == summary.username
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await second.me()
        assert excinfo.value.status_code == 401

    async with TwinlabClient(config.base_url) as fresh:
        with pytest.raises(TwinlabApiError) as rejected:
            _ = await fresh.login(summary.username, DEFAULT_PASSWORD)
        assert rejected.value.status_code == 401
        info = await fresh.login(summary.username, ALTERNATE_PASSWORD)
        assert info.username == summary.username
