"""API-key contract: self-service Bearer credentials acting as their creator."""

from collections.abc import Callable

import httpx
import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import DEFAULT_PASSWORD, SuiteConfig, UserClientFactory


async def test_api_key_lifecycle(config: SuiteConfig, make_user_client: UserClientFactory) -> None:
    summary, client = await make_user_client(None)

    created = await client.create_api_key("ci")
    assert created.key  # the secret, returned only here
    assert created.info.name == "ci"
    assert created.info.last_used_at is None

    # The listing carries exactly the created key's metadata.
    listed = await client.list_api_keys()
    assert listed == [created.info]

    # Wire-level probe (the suite's one deliberate raw-HTTP exception, see
    # README): the typed client cannot observe extra wire fields, but the
    # secret must never appear in the listing payload.
    async with httpx.AsyncClient(base_url=config.base_url) as raw:
        response = await raw.get(
            "/api/v1/auth/api-keys", headers={"Authorization": f"Bearer {created.key}"}
        )
        assert response.status_code == 200
        assert created.key not in response.text

    # The key authenticates as its creating user, with that user's
    # permissions — including on a real permissioned route, not just /auth/me.
    async with TwinlabClient(config.base_url, api_key=created.key) as keyed:
        info = await keyed.me()
        assert info.username == summary.username
        _ = await keyed.list_labs()  # any authenticated user; no access = []

    # Using the key stamps last_used_at.
    used = await client.list_api_keys()
    assert used[0].last_used_at is not None

    await client.revoke_api_key(created.info.id)
    assert await client.list_api_keys() == []
    async with TwinlabClient(config.base_url, api_key=created.key) as keyed:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await keyed.me()
        assert excinfo.value.status_code == 401


async def test_api_key_duplicate_name_is_409(make_user_client: UserClientFactory) -> None:
    _, client = await make_user_client(None)
    _ = await client.create_api_key("ci")
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await client.create_api_key("ci")
    assert excinfo.value.status_code == 409


async def test_deactivating_the_user_stops_their_keys(
    admin: TwinlabClient, config: SuiteConfig, make_user_client: UserClientFactory
) -> None:
    summary, client = await make_user_client(None)
    created = await client.create_api_key("ci")

    _ = await admin.set_user_active(summary.id, False)
    async with TwinlabClient(config.base_url, api_key=created.key) as keyed:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await keyed.me()
        assert excinfo.value.status_code == 401


async def test_deleting_the_user_kills_their_keys(
    admin: TwinlabClient, config: SuiteConfig, unique: Callable[[str], str]
) -> None:
    # Not via make_user_client: the user is deleted mid-test, so the factory's
    # teardown would double-delete.
    summary = await admin.create_user(unique("user"), DEFAULT_PASSWORD)
    async with TwinlabClient(config.base_url) as owner:
        _ = await owner.login(summary.username, DEFAULT_PASSWORD)
        created = await owner.create_api_key("ci")

    await admin.delete_user(summary.id)
    async with TwinlabClient(config.base_url, api_key=created.key) as keyed:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await keyed.me()
        assert excinfo.value.status_code == 401
