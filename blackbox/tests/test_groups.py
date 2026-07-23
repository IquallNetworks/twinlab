"""Group contract (global group:manage): CRUD, membership, role inheritance."""

import uuid

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import GroupFactory, UserClientFactory


async def test_create_group_roundtrip(admin: TwinlabClient, make_group: GroupFactory) -> None:
    group = await make_group()
    assert group.description == "black-box test group"
    assert group.members == []
    assert group.roles == set()

    listed = {entry.id: entry for entry in await admin.list_groups()}
    assert listed[group.id] == group


async def test_duplicate_group_name_is_409(admin: TwinlabClient, make_group: GroupFactory) -> None:
    group = await make_group()
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_group(group.name)
    assert excinfo.value.status_code == 409


async def test_get_group_matches_list(admin: TwinlabClient, make_group: GroupFactory) -> None:
    group = await make_group()
    assert await admin.get_group(group.id) == group


async def test_get_unknown_group_is_404(admin: TwinlabClient) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.get_group(uuid.uuid4())
    assert excinfo.value.status_code == 404


async def test_set_members_full_replace(
    admin: TwinlabClient, make_group: GroupFactory, make_user_client: UserClientFactory
) -> None:
    group = await make_group()
    first, _ = await make_user_client(None)
    second, _ = await make_user_client(None)

    both = await admin.set_group_members(group.id, [first.id, second.id])
    assert {member.id for member in both.members} == {first.id, second.id}
    assert {member.username for member in both.members} == {first.username, second.username}

    only_second = await admin.set_group_members(group.id, [second.id])
    assert {member.id for member in only_second.members} == {second.id}


async def test_set_members_unknown_user_is_422(
    admin: TwinlabClient, make_group: GroupFactory
) -> None:
    group = await make_group()
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.set_group_members(group.id, [uuid.uuid4()])
    assert excinfo.value.status_code == 422


async def test_group_roles_are_global_only(admin: TwinlabClient, make_group: GroupFactory) -> None:
    group = await make_group()
    granted = await admin.set_group_roles(group.id, {"global_viewer"})
    assert granted.roles == {"global_viewer"}

    # Lab-scoped roles bind through lab grants, never through group roles.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.set_group_roles(group.id, {"lab_viewer"})
    assert excinfo.value.status_code == 422


async def test_membership_confers_group_permissions(
    admin: TwinlabClient, make_group: GroupFactory, make_user_client: UserClientFactory
) -> None:
    group = await make_group()
    _ = await admin.set_group_roles(group.id, {"global_viewer"})
    summary, client = await make_user_client(None)

    before = await client.me()
    assert "lab:read" not in before.permissions

    _ = await admin.set_group_members(group.id, [summary.id])
    joined = await client.me()
    assert "lab:read" in joined.permissions

    # Deleting the group cascades its bindings; the inherited permission goes.
    await admin.delete_group(group.id)
    left = await client.me()
    assert "lab:read" not in left.permissions


async def test_delete_group(admin: TwinlabClient, make_group: GroupFactory) -> None:
    group = await make_group()
    await admin.delete_group(group.id)
    assert group.id not in {entry.id for entry in await admin.list_groups()}
    with pytest.raises(TwinlabApiError) as excinfo:
        await admin.delete_group(group.id)
    assert excinfo.value.status_code == 404


async def test_groups_endpoints_require_group_manage(
    make_user_client: UserClientFactory,
) -> None:
    _, plain = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await plain.list_groups()
    assert excinfo.value.status_code == 403
