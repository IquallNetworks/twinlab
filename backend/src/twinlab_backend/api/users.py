"""User-management endpoints. All require the global `user:manage` permission.

A user's `roles` here are their **global** roles (global role bindings); lab-scoped
access is granted per lab via the lab-grants API.
"""

import uuid
from datetime import datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import select

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth import user_management
from twinlab_backend.auth.dependencies import require_global
from twinlab_backend.auth.sessions import revoke_all_for_user
from twinlab_backend.auth.user_management import UserError, create_user, list_users, set_roles
from twinlab_backend.config import is_email_address
from twinlab_backend.db.models import RoleBinding, User, UserIdentity
from twinlab_backend.deps import SessionDep
from twinlab_backend.result import Err

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_global(perms.USER_MANAGE))],
)


def _email(value: str) -> str:
    if not is_email_address(value):
        raise ValueError("not an email address")
    return value


# Contract delta 33. The email check is structural only (config.is_email_address);
# 320 is RFC 5321's ceiling and the column width.
EmailAddress = Annotated[str, Field(min_length=3, max_length=320), AfterValidator(_email)]
DisplayName = Annotated[str, Field(min_length=1, max_length=128)]


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailAddress
    display_name: DisplayName
    # Omitted (or null) = the server generates one and returns it ONCE.
    password: str | None = Field(default=None, min_length=8)
    roles: list[str] = Field(default_factory=list)


class SetProfileRequest(BaseModel):
    email: EmailAddress
    display_name: DisplayName


class SetRolesRequest(BaseModel):
    roles: list[str]


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class SetActiveRequest(BaseModel):
    is_active: bool


class LinkedIdentityOut(BaseModel):
    id: uuid.UUID
    provider: str  # the provider's name
    subject: str
    email_at_link: str
    created_at: datetime
    last_login_at: datetime | None


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str
    is_active: bool
    roles: list[str]  # global roles
    identities: list[LinkedIdentityOut]


class UserCreatedOut(BaseModel):
    user: UserSummary
    # Set only when the request omitted the password — the only time it is shown.
    generated_password: str | None


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


def _identity_out(row: UserIdentity) -> LinkedIdentityOut:
    return LinkedIdentityOut(
        id=row.id,
        provider=row.provider.name,
        subject=row.subject,
        email_at_link=row.email_at_link,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


def _summary(user: User, roles: list[str], identities: list[UserIdentity]) -> UserSummary:
    return UserSummary(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=roles,
        identities=[_identity_out(row) for row in identities],
    )


async def summary_of(db: SessionDep, user: User) -> UserSummary:
    """One user's summary, read fresh (roles and identities)."""
    roles = (await _global_roles_by_user(db)).get(user.id, [])
    identities = (await user_management.identities_by_user(db)).get(user.id, [])
    return _summary(user, roles, identities)


# Conflicts -> 409; missing user/identity -> 404; unknown_roles -> 422.
_STATUS = {
    "username_taken": 409,
    "email_taken": 409,
    "last_admin": 409,
    "user_not_found": 404,
    "identity_not_found": 404,
    "unknown_roles": 422,
}


def _raise(error: UserError) -> NoReturn:
    raise ApiError(_STATUS[error.reason], error.reason, error.detail)


@router.post("", status_code=201)
async def create(body: CreateUserRequest, db: SessionDep) -> UserCreatedOut:
    result = await create_user(
        db,
        username=body.username,
        email=body.email,
        display_name=body.display_name,
        password=body.password,
        role_names=body.roles,
        commit=True,
    )
    if isinstance(result, Err):
        _raise(result.error)
    return UserCreatedOut(
        user=await summary_of(db, result.value.user),
        generated_password=result.value.generated_password,
    )


@router.get("")
async def list_all(db: SessionDep) -> list[UserSummary]:
    roles_by_user = await _global_roles_by_user(db)
    identities = await user_management.identities_by_user(db)
    return [
        _summary(user, roles_by_user.get(user.id, []), identities.get(user.id, []))
        for user in await list_users(db)
    ]


@router.get("/{user_id}")
async def get_one(user_id: uuid.UUID, db: SessionDep) -> UserSummary:
    user = await user_management.get_user(db, user_id)
    if user is None:
        _raise(UserError("user_not_found"))
    return await summary_of(db, user)


@router.put("/{user_id}/profile")
async def update_profile(
    user_id: uuid.UUID, body: SetProfileRequest, db: SessionDep
) -> UserSummary:
    # Any user, the caller included — how an admin replaces their own
    # backfilled `<username>@users.invalid` (delta 33).
    result = await user_management.set_profile(
        db, user_id, email=body.email, display_name=body.display_name
    )
    if isinstance(result, Err):
        _raise(result.error)
    return await summary_of(db, result.value)


@router.delete("/{user_id}/identities/{identity_id}", status_code=204)
async def unlink_identity(user_id: uuid.UUID, identity_id: uuid.UUID, db: SessionDep) -> None:
    result = await user_management.unlink_identity(db, user_id, identity_id)
    if isinstance(result, Err):
        _raise(result.error)


@router.put("/{user_id}/roles")
async def update_roles(user_id: uuid.UUID, body: SetRolesRequest, db: SessionDep) -> UserSummary:
    result = await set_roles(db, user_id, body.roles)
    if isinstance(result, Err):
        _raise(result.error)
    return await summary_of(db, result.value)


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
    return await summary_of(db, result.value)


@router.delete("/{user_id}", status_code=204)
async def delete(user_id: uuid.UUID, db: SessionDep) -> None:
    result = await user_management.delete_user(db, user_id)
    if isinstance(result, Err):
        _raise(result.error)
