"""Group-management endpoints. All require the global `group:manage` permission.

A group is an admin-defined set of users; a group can hold global roles (here) and
lab-scoped grants (via the lab-grants API). Every member inherits the group's
bindings, so access is curated by membership rather than re-granted per user.
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import require_global
from twinlab_backend.db.models import Group
from twinlab_backend.deps import SessionDep
from twinlab_backend.services import rbac_store

router = APIRouter(
    prefix="/groups",
    tags=["groups"],
    dependencies=[Depends(require_global(perms.GROUP_MANAGE))],
)


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)


class SetMembersRequest(BaseModel):
    user_ids: list[uuid.UUID]


class SetGroupRolesRequest(BaseModel):
    roles: list[str]


class GroupMember(BaseModel):
    id: uuid.UUID
    username: str


class GroupSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    members: list[GroupMember]
    roles: list[str]  # global roles held by the group


def _raise(error: rbac_store.RbacStoreError) -> NoReturn:
    status = {"name_taken": 409, "group_not_found": 404, "user_not_found": 422}.get(
        error.reason, 422
    )
    raise HTTPException(status_code=status, detail={"reason": error.reason, "detail": error.detail})


async def _summary(db: SessionDep, group_id: uuid.UUID) -> GroupSummary:
    # Re-query with members eagerly loaded: a group instance handed back straight
    # from a commit has its attributes expired, and touching the relationship then
    # would trigger a sync lazy-load (MissingGreenlet) in this async context.
    group = await db.scalar(
        select(Group).options(selectinload(Group.members)).where(Group.id == group_id)
    )
    if group is None:  # the group was just created/verified; absence is an internal fault
        raise HTTPException(status_code=404, detail={"reason": "group_not_found", "detail": ""})
    roles = await rbac_store.global_role_names_for(db, perms.PRINCIPAL_GROUP, group.id)
    return GroupSummary(
        id=group.id,
        name=group.name,
        description=group.description,
        members=[GroupMember(id=m.id, username=m.username) for m in group.members],
        roles=roles,
    )


def _validate_global_roles(role_names: list[str]) -> None:
    bad = sorted(
        name for name in set(role_names) if not perms.role_bindable_at(name, perms.SCOPE_GLOBAL)
    )
    if bad:
        raise HTTPException(
            status_code=422,
            detail={"reason": "unknown_roles", "detail": ", ".join(bad)},
        )


@router.post("", status_code=201)
async def create(body: CreateGroupRequest, db: SessionDep) -> GroupSummary:
    result = await rbac_store.create_group(db, body.name, body.description)
    if isinstance(result, rbac_store.RbacStoreError):
        _raise(result)
    return await _summary(db, result.id)


@router.get("")
async def list_all(db: SessionDep) -> list[GroupSummary]:
    return [await _summary(db, group.id) for group in await rbac_store.list_groups(db)]


@router.delete("/{group_id}", status_code=204)
async def delete(group_id: uuid.UUID, db: SessionDep) -> None:
    result = await rbac_store.delete_group(db, group_id)
    if isinstance(result, rbac_store.RbacStoreError):
        _raise(result)


@router.put("/{group_id}/members")
async def set_members(group_id: uuid.UUID, body: SetMembersRequest, db: SessionDep) -> GroupSummary:
    result = await rbac_store.set_group_members(db, group_id, body.user_ids)
    if isinstance(result, rbac_store.RbacStoreError):
        _raise(result)
    return await _summary(db, result.id)


@router.put("/{group_id}/roles")
async def set_roles(
    group_id: uuid.UUID, body: SetGroupRolesRequest, db: SessionDep
) -> GroupSummary:
    group = await rbac_store.get_group(db, group_id)
    if group is None:
        _raise(rbac_store.RbacStoreError("group_not_found"))
    _validate_global_roles(body.roles)
    await rbac_store.set_principal_global_roles(
        db,
        principal_type=perms.PRINCIPAL_GROUP,
        principal_id=group_id,
        role_names=body.roles,
        granted_by=None,
    )
    return await _summary(db, group_id)
