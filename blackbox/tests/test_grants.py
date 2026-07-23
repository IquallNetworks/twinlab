"""Lab grants & ownership: delegation, anti-escalation, existence-hiding."""

import uuid

import pytest
from twinlab_client import Principal, TwinlabApiError, TwinlabClient

from _config import (
    LAB_SCOPED_PERMISSIONS,
    LINUX_LAB_DEFINITION,
    GroupFactory,
    LabFactory,
    UserClientFactory,
)


async def test_grants_start_empty(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    assert await admin.list_grants(lab.name) == []


async def test_grant_lab_viewer_grants_read_only(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    summary, viewer = await make_user_client(None)

    grant = await admin.create_grant(lab.name, "user", summary.id, "lab_viewer")
    assert grant.principal_type == "user"
    assert grant.principal_id == summary.id
    assert grant.principal_name == summary.username
    assert grant.role == "lab_viewer"

    rows = {row.name: row for row in await viewer.list_labs()}
    assert rows[lab.name].permissions == {"lab:read"}
    detail = await viewer.get_lab(lab.name)
    assert detail.permissions == {"lab:read"}
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await viewer.update_definition(lab.name, LINUX_LAB_DEFINITION)
    assert excinfo.value.status_code == 403


async def test_duplicate_grant_is_idempotent(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    summary, _ = await make_user_client(None)

    _ = await admin.create_grant(lab.name, "user", summary.id, "lab_viewer")
    _ = await admin.create_grant(lab.name, "user", summary.id, "lab_viewer")
    grants = await admin.list_grants(lab.name)
    assert len(grants) == 1


async def test_grant_global_only_role_is_422(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    summary, _ = await make_user_client(None)
    for role in ("creator", "bb-no-such-role"):
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await admin.create_grant(lab.name, "user", summary.id, role)
        assert excinfo.value.status_code == 422, role


async def test_delete_grant_revokes_access(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    summary, viewer = await make_user_client(None)
    grant = await admin.create_grant(lab.name, "user", summary.id, "lab_viewer")
    _ = await viewer.get_lab(lab.name)

    await admin.delete_grant(lab.name, grant.id)
    with pytest.raises(TwinlabApiError) as revoked:
        _ = await viewer.get_lab(lab.name)
    assert revoked.value.status_code == 404  # back to existence-hiding

    with pytest.raises(TwinlabApiError) as gone:
        await admin.delete_grant(lab.name, grant.id)
    assert gone.value.status_code == 404


async def test_grantee_without_lab_grant_cannot_delegate(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    viewer_summary, viewer = await make_user_client(None)
    other_summary, _ = await make_user_client(None)
    _ = await admin.create_grant(lab.name, "user", viewer_summary.id, "lab_viewer")

    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await viewer.create_grant(lab.name, "user", other_summary.id, "lab_viewer")
    assert excinfo.value.status_code == 403


async def test_anti_escalation(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    # lab_manager holds lab:grant but not the full owner set (no lab:destroy),
    # so it can delegate roles up to its own level and no further.
    lab = await make_lab(None)
    manager_summary, manager = await make_user_client(None)
    target_summary, _ = await make_user_client(None)
    _ = await admin.create_grant(lab.name, "user", manager_summary.id, "lab_manager")

    delegated = await manager.create_grant(lab.name, "user", target_summary.id, "lab_viewer")
    assert delegated.role == "lab_viewer"

    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await manager.create_grant(lab.name, "user", target_summary.id, "lab_owner")
    assert excinfo.value.status_code == 403


async def test_group_grant_and_cascade(
    admin: TwinlabClient,
    make_lab: LabFactory,
    make_group: GroupFactory,
    make_user_client: UserClientFactory,
) -> None:
    lab = await make_lab(None)
    group = await make_group()
    summary, member = await make_user_client(None)
    _ = await admin.set_group_members(group.id, [summary.id])

    grant = await admin.create_grant(lab.name, "group", group.id, "lab_viewer")
    assert grant.principal_name == group.name
    detail = await member.get_lab(lab.name)
    assert detail.permissions == {"lab:read"}

    # Deleting the group cascades its bindings — access goes with it.
    await admin.delete_group(group.id)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await member.get_lab(lab.name)
    assert excinfo.value.status_code == 404
    assert await admin.list_grants(lab.name) == []


async def test_transfer_owner(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    summary, new_owner = await make_user_client(None)

    result = await admin.transfer_owner(lab.name, summary.id)
    assert result.lab == lab.name
    assert result.owner == Principal(id=summary.id, name=summary.username)

    detail = await new_owner.get_lab(lab.name)
    assert detail.owner == Principal(id=summary.id, name=summary.username)
    assert detail.permissions >= LAB_SCOPED_PERMISSIONS  # owner-implicit

    # The admin still reads it through global permissions.
    _ = await admin.get_lab(lab.name)


async def test_transfer_owner_unknown_user_is_404(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.transfer_owner(lab.name, uuid.uuid4())
    assert excinfo.value.status_code == 404


async def test_transfer_owner_requires_owner_equivalence(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    manager_summary, manager = await make_user_client(None)
    target_summary, _ = await make_user_client(None)
    # lab_manager lacks lab:destroy, so it is not owner-equivalent.
    _ = await admin.create_grant(lab.name, "user", manager_summary.id, "lab_manager")

    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await manager.transfer_owner(lab.name, target_summary.id)
    assert excinfo.value.status_code == 403
