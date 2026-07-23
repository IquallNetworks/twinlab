import uuid

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.service import Grant, resolve_permissions

_LAB_A = uuid.uuid4()
_LAB_B = uuid.uuid4()


def _global(role: str) -> Grant:
    return Grant(role_name=role, scope_type=perms.SCOPE_GLOBAL, lab_id=None)


def _lab(role: str, lab_id: uuid.UUID) -> Grant:
    return Grant(role_name=role, scope_type=perms.SCOPE_LAB, lab_id=lab_id)


def test_global_binding_contributes_full_permissions() -> None:
    # A global admin binding grants everything, on any lab.
    got = resolve_permissions([_global("admin")], _LAB_A, is_owner=False)
    assert got == set(perms.ALL_PERMISSIONS)


def test_global_viewer_reads_every_lab() -> None:
    got = resolve_permissions([_global("global_viewer")], _LAB_A, is_owner=False)
    assert got == {perms.LAB_READ}


def test_lab_binding_applies_only_to_its_lab() -> None:
    grants = [_lab("lab_manager", _LAB_A)]
    on_a = resolve_permissions(grants, _LAB_A, is_owner=False)
    on_b = resolve_permissions(grants, _LAB_B, is_owner=False)
    assert perms.LAB_EDIT in on_a
    assert on_b == set()  # the grant is for lab A, not lab B


def test_owner_gets_implicit_owner_permissions() -> None:
    # No binding at all, but the caller owns the lab -> full lab_owner set.
    got = resolve_permissions([], _LAB_A, is_owner=True)
    assert got == set(perms.LAB_OWNER_PERMISSIONS)
    assert perms.LAB_DESTROY in got and perms.LAB_GRANT in got


def test_global_check_ignores_lab_bindings() -> None:
    # Evaluated globally (lab_id=None), a lab-scoped grant contributes nothing — so a
    # user with only a lab grant has no global permissions (e.g. can't create labs).
    got = resolve_permissions([_lab("lab_owner", _LAB_A)], None, is_owner=False)
    assert got == set()


def test_unknown_role_grants_nothing() -> None:
    # A binding to a role removed from the catalog is inert, not an error.
    assert resolve_permissions([_global("obsolete")], _LAB_A, is_owner=False) == set()


def test_permissions_union_across_grants() -> None:
    grants = [_global("global_viewer"), _lab("lab_operator", _LAB_A)]
    got = resolve_permissions(grants, _LAB_A, is_owner=False)
    assert {perms.LAB_READ, perms.LAB_CONFIGURE, perms.LAB_VALIDATE, perms.LAB_TERMINAL} <= got
    assert perms.LAB_EDIT not in got  # operator can't edit
