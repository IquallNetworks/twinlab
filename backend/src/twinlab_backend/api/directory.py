"""A minimal principal directory: user and group names + ids.

The lab-grants UI needs to pick a grantee, but a lab owner who holds only `lab:grant`
(not the global `user:manage`/`group:manage`) can't call the full users/groups
endpoints. This exposes just id + display name for users and groups to any
authenticated caller — enough to grant to someone, without the roles/status/membership
detail those management endpoints carry.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.db.models import Group, User
from twinlab_backend.deps import SessionDep

router = APIRouter(prefix="/principals", tags=["principals"])


class Principal(BaseModel):
    id: uuid.UUID
    name: str


class PrincipalsResponse(BaseModel):
    users: list[Principal]
    groups: list[Principal]


@router.get("")
async def list_principals(_: CurrentUserDep, db: SessionDep) -> PrincipalsResponse:
    users = (await db.scalars(select(User).order_by(User.username))).all()
    groups = (await db.scalars(select(Group).order_by(Group.name))).all()
    return PrincipalsResponse(
        users=[Principal(id=u.id, name=u.username) for u in users],
        groups=[Principal(id=g.id, name=g.name) for g in groups],
    )
