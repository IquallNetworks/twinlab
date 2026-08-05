"""Role catalog, principals directory, and the device catalog (any
authenticated user)."""

from twinlab_client import TwinlabClient

from _config import LAB_SCOPED_PERMISSIONS, GroupFactory, UserClientFactory

# Pinned in the contract's shipped-catalogs appendix (docs/
# twinlab_client_shape.py): a catalog change is a contract + suite change.
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


async def test_device_catalog_serves_supported_set(admin: TwinlabClient) -> None:
    catalog = await admin.device_catalog()
    by_device = {device.device: device for device in catalog.devices}
    # The tested platforms (CLAUDE.md Current State) plus the linux host.
    assert set(by_device) == {"vyos", "iol", "frr", "routeros7", "bird", "dnsmasq", "linux"}

    # The builder's proven module set must be advertised by the full routers.
    for router in ("vyos", "iol", "frr", "routeros7"):
        assert by_device[router].role == "router"
        assert set(by_device[router].modules) >= {"ospf", "bgp", "mpls", "vrf"}, router
    # bird routes but has no MPLS in netlab's clab matrix; the daemon serving
    # DHCP and the plain container are hosts.
    assert by_device["bird"].role == "router"
    assert set(by_device["bird"].modules) >= {"ospf", "bgp"}
    for host in ("dnsmasq", "linux"):
        assert by_device[host].role == "host"

    for device in catalog.devices:
        assert device.label
        assert device.image
        # Presence is best-effort truth about THIS host, so assert its type,
        # not its value — except that live must pin the None-ness either way.
        if catalog.live:
            assert device.image_present is not None
        else:
            assert device.image_present is None

    # The compose stack ships the runner, so a healthy stack answers live.
    assert catalog.live


async def test_device_catalog_visible_without_admin_roles(
    make_user_client: UserClientFactory,
) -> None:
    _, plain = await make_user_client(None)
    catalog = await plain.device_catalog()
    assert {device.device for device in catalog.devices} == {
        "vyos",
        "iol",
        "frr",
        "routeros7",
        "bird",
        "dnsmasq",
        "linux",
    }


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
