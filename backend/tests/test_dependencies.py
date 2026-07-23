import pytest
from fastapi import HTTPException

from twinlab_backend.auth.dependencies import require
from twinlab_backend.db.models import Permission, Role, User


def _user_with(*permission_names: str) -> User:
    role = Role(name="r")
    role.permissions = [Permission(name=n) for n in permission_names]
    user = User(username="u", password_hash="x")
    user.roles = [role]
    return user


async def test_require_allows_when_permission_present() -> None:
    guard = require("lab:create")
    user = _user_with("lab:create", "lab:read")
    assert await guard(user) is user


async def test_require_forbids_when_permission_absent() -> None:
    guard = require("lab:destroy")
    user = _user_with("lab:read")
    with pytest.raises(HTTPException) as excinfo:
        await guard(user)
    assert excinfo.value.status_code == 403
