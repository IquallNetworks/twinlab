"""API-key contract: self-service Bearer credentials acting as their creator."""

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import SuiteConfig, UserClientFactory


async def test_api_key_lifecycle(config: SuiteConfig, make_user_client: UserClientFactory) -> None:
    summary, client = await make_user_client(None)

    created = await client.create_api_key("ci")
    assert created.key  # the secret, returned only here
    assert created.info.name == "ci"
    assert created.info.last_used_at is None

    # Listings show metadata, never the secret (ApiKey has no key field).
    listed = await client.list_api_keys()
    assert [key.id for key in listed] == [created.info.id]

    # The key authenticates as its creating user, with that user's permissions.
    async with TwinlabClient(config.base_url, api_key=created.key) as keyed:
        info = await keyed.me()
        assert info.username == summary.username

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
