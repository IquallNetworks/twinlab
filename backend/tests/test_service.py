from twinlab_backend.auth.service import effective_permissions
from twinlab_backend.db.models import Permission, Role, User


def test_effective_permissions_unions_roles() -> None:
    read = Permission(name="lab:read")
    create = Permission(name="lab:create")

    viewer = Role(name="viewer")
    viewer.permissions = [read]
    operator = Role(name="operator")
    operator.permissions = [read, create]

    user = User(username="u", password_hash="x")
    user.roles = [viewer, operator]

    assert effective_permissions(user) == {"lab:read", "lab:create"}


def test_effective_permissions_empty_without_roles() -> None:
    user = User(username="u", password_hash="x")
    user.roles = []
    assert effective_permissions(user) == set()
