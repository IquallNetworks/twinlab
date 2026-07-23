"""Permission/role catalog invariants and the anti-escalation property.

The route guards themselves are DB-backed and covered by the live integration path;
here we lock down the pure catalog the resolver and grant checks depend on.
"""

from twinlab_backend.auth import permissions as perms


def test_lab_roles_carry_only_lab_scoped_permissions() -> None:
    for name in perms.lab_bindable_roles():
        assert perms.role_permissions(name) <= perms.LAB_SCOPED_PERMISSIONS, name


def test_global_only_permissions_never_in_a_lab_role() -> None:
    for name in perms.lab_bindable_roles():
        assert not (perms.role_permissions(name) & perms.GLOBAL_ONLY_PERMISSIONS), name


def test_admin_holds_every_permission_globally() -> None:
    spec = perms.ROLE_CATALOG[perms.ADMIN_ROLE]
    assert spec.permissions == set(perms.ALL_PERMISSIONS)
    assert spec.scopes == {perms.SCOPE_GLOBAL}


def test_default_user_role_has_no_permissions() -> None:
    assert perms.role_permissions(perms.DEFAULT_USER_ROLE) == frozenset()


def test_role_bindable_at_matches_scopes() -> None:
    assert perms.role_bindable_at("lab_viewer", perms.SCOPE_LAB)
    assert not perms.role_bindable_at("lab_viewer", perms.SCOPE_GLOBAL)
    assert perms.role_bindable_at("global_viewer", perms.SCOPE_GLOBAL)
    assert not perms.role_bindable_at("global_viewer", perms.SCOPE_LAB)
    assert not perms.role_bindable_at("does_not_exist", perms.SCOPE_LAB)


def test_manager_cannot_grant_owner_but_can_grant_peers() -> None:
    # Anti-escalation is a subset test: a lab_manager (no destroy) cannot grant
    # lab_owner (which has destroy), but can grant manager/operator/viewer.
    manager = perms.role_permissions("lab_manager")
    assert not perms.role_permissions("lab_owner").issubset(manager)
    assert perms.role_permissions("lab_manager").issubset(manager)
    assert perms.role_permissions("lab_operator").issubset(manager)
    assert perms.role_permissions("lab_viewer").issubset(manager)


def test_owner_can_grant_any_lab_role() -> None:
    owner = perms.LAB_OWNER_PERMISSIONS
    for name in perms.lab_bindable_roles():
        assert perms.role_permissions(name).issubset(owner), name
