"""User-management endpoints. All require the global `user:manage` permission.

A user's `roles` here are their **global** roles (global role bindings); lab-scoped
access is granted per lab via the lab-grants API.
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth import user_management
from twinlab_backend.auth.dependencies import require_global
from twinlab_backend.auth.sessions import revoke_all_for_user
from twinlab_backend.auth.user_management import UserError, create_user, list_users, set_roles
from twinlab_backend.db.models import RoleBinding, User
from twinlab_backend.deps import SessionDep
from twinlab_backend.result import Err

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_global(perms.USER_MANAGE))],
)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)
    roles: list[str] = Field(default_factory=list)


class SetRolesRequest(BaseModel):
    roles: list[str]


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class SetActiveRequest(BaseModel):
    is_active: bool


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    is_active: bool
    roles: list[str]  # global roles


async def _global_roles_by_user(db: SessionDep) -> dict[uuid.UUID, list[str]]:
    """All users' global role names in one query, keyed by user id — avoids an N+1
    when listing."""
    rows = (
        await db.scalars(
            select(RoleBinding).where(
                RoleBinding.principal_type == perms.PRINCIPAL_USER,
                RoleBinding.scope_type == perms.SCOPE_GLOBAL,
            )
        )
    ).all()
    by_user: dict[uuid.UUID, list[str]] = {}
    for binding in rows:
        by_user.setdefault(binding.principal_id, []).append(binding.role_name)
    return {uid: sorted(set(names)) for uid, names in by_user.items()}


def _summary(user: User, roles: list[str]) -> UserSummary:
    return UserSummary(id=user.id, username=user.username, is_active=user.is_active, roles=roles)


# username_taken/last_admin -> 409; user_not_found -> 404; unknown_roles -> 422.
def _raise(error: UserError) -> NoReturn:
    status = {"username_taken": 409, "last_admin": 409, "user_not_found": 404}.get(
        error.reason, 422
    )
    raise ApiError(status, error.reason, error.detail)


@router.post("", status_code=201)
async def create(body: CreateUserRequest, db: SessionDep) -> UserSummary:
    result = await create_user(db, body.username, body.password, body.roles)
    if isinstance(result, Err):
        _raise(result.error)
    roles = (await _global_roles_by_user(db)).get(result.value.id, [])
    return _summary(result.value, roles)


@router.get("")
async def list_all(db: SessionDep) -> list[UserSummary]:
    roles_by_user = await _global_roles_by_user(db)
    return [_summary(user, roles_by_user.get(user.id, [])) for user in await list_users(db)]


@router.get("/{user_id}")
async def get_one(user_id: uuid.UUID, db: SessionDep) -> UserSummary:
    user = await user_management.get_user(db, user_id)
    if user is None:
        _raise(UserError("user_not_found"))
    roles = (await _global_roles_by_user(db)).get(user.id, [])
    return _summary(user, roles)


@router.put("/{user_id}/roles")
async def update_roles(user_id: uuid.UUID, body: SetRolesRequest, db: SessionDep) -> UserSummary:
    result = await set_roles(db, user_id, body.roles)
    if isinstance(result, Err):
        _raise(result.error)
    roles = (await _global_roles_by_user(db)).get(result.value.id, [])
    return _summary(result.value, roles)


@router.put("/{user_id}/password", status_code=204)
async def reset_password(user_id: uuid.UUID, body: SetPasswordRequest, db: SessionDep) -> None:
    # Admin reset: no current password needed, and ALL the user's sessions are
    # revoked (unlike the self-service change, which keeps the caller's own).
    result = await user_management.set_password(db, user_id, body.password)
    if isinstance(result, Err):
        _raise(result.error)
    await revoke_all_for_user(db, user_id)


@router.put("/{user_id}/active")
async def set_active(user_id: uuid.UUID, body: SetActiveRequest, db: SessionDep) -> UserSummary:
    # Deactivation revokes sessions and stops API keys (both check is_active on
    # resolve); the record, bindings, and owned labs are untouched — the
    # reversible soft alternative to delete. Refuses the last active admin.
    result = await user_management.set_active(db, user_id, body.is_active)
    if isinstance(result, Err):
        _raise(result.error)
    if not body.is_active:
        await revoke_all_for_user(db, user_id)
    roles = (await _global_roles_by_user(db)).get(result.value.id, [])
    return _summary(result.value, roles)


@router.delete("/{user_id}", status_code=204)
async def delete(user_id: uuid.UUID, db: SessionDep) -> None:
    result = await user_management.delete_user(db, user_id)
    if isinstance(result, Err):
        _raise(result.error)
