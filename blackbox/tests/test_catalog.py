"""Role catalog and principals directory (any authenticated user)."""

from twinlab_client import TwinlabClient

from _config import LAB_SCOPED_PERMISSIONS, GroupFactory, UserClientFactory

_EXPECTED_ROLES = frozenset(
    {
        "admin",
        "global_operator",
        "global_viewer",
        "creator",
        "user",
        "lab_owner",
        "lab_manager",
        "lab_operator",
        "lab_viewer",
    }
)


async def test_role_catalog_shapes(admin: TwinlabClient) -> None:
    catalog = {role.name: role for role in await admin.list_roles()}
    assert set(catalog) >= _EXPECTED_ROLES

    assert catalog["admin"].scopes == {"global"}
    assert catalog["lab_viewer"].scopes == {"lab"}
    assert catalog["lab_viewer"].permissions == {"lab:read"}
    # The baseline role: authenticated, no inherent access.
    assert catalog["user"].permissions == set()

    # Lab-bindable roles carry only lab-scoped permissions.
    for role in catalog.values():
        if "lab" in role.scopes:
            assert role.permissions <= LAB_SCOPED_PERMISSIONS, role.name

    # The anti-escalation lever the grants tests rely on: lab_manager can
    # delegate (lab:grant) but does not hold the full owner set (no destroy).
    assert "lab:grant" in catalog["lab_manager"].permissions
    assert "lab:destroy" not in catalog["lab_manager"].permissions


async def test_catalog_visible_without_admin_roles(
    make_user_client: UserClientFactory,
) -> None:
    _, plain = await make_user_client(None)
    catalog = {role.name for role in await plain.list_roles()}
    assert catalog >= _EXPECTED_ROLES


async def test_principals_visible_to_any_authenticated_user(
    make_user_client: UserClientFactory, make_group: GroupFactory
) -> None:
    group = await make_group()
    summary, plain = await make_user_client(None)

    principals = await plain.list_principals()
    users_by_id = {principal.id: principal.name for principal in principals.users}
    groups_by_id = {principal.id: principal.name for principal in principals.groups}
    assert users_by_id.get(summary.id) == summary.username
    assert groups_by_id.get(group.id) == group.name
