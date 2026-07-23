"""User-management endpoints. All require the `user:manage` permission."""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import require
from twinlab_backend.auth.user_management import UserError, create_user, list_users, set_roles
from twinlab_backend.db.models import User
from twinlab_backend.deps import SessionDep
from twinlab_backend.result import Err

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require(perms.USER_MANAGE))],
)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)
    roles: list[str] = Field(default_factory=list)


class SetRolesRequest(BaseModel):
    roles: list[str]


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    is_active: bool
    roles: list[str]


def _summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        roles=sorted(role.name for role in user.roles),
    )


# username_taken -> 409; user_not_found -> 404; unknown_roles -> 422.
def _raise(error: UserError) -> NoReturn:
    status = {"username_taken": 409, "user_not_found": 404}.get(error.reason, 422)
    raise HTTPException(status_code=status, detail={"reason": error.reason, "detail": error.detail})


@router.post("", status_code=201)
async def create(body: CreateUserRequest, db: SessionDep) -> UserSummary:
    result = await create_user(db, body.username, body.password, body.roles)
    if isinstance(result, Err):
        _raise(result.error)
    return _summary(result.value)


@router.get("")
async def list_all(db: SessionDep) -> list[UserSummary]:
    return [_summary(user) for user in await list_users(db)]


@router.put("/{user_id}/roles")
async def update_roles(user_id: uuid.UUID, body: SetRolesRequest, db: SessionDep) -> UserSummary:
    result = await set_roles(db, user_id, body.roles)
    if isinstance(result, Err):
        _raise(result.error)
    return _summary(result.value)
