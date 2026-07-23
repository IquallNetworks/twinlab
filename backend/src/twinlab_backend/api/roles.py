"""Read-only role catalog: what roles exist, their scopes, and their permissions.

Served from the code catalog (the source of truth), so the frontend can populate
role pickers for users, groups, and lab grants without hardcoding the list. Any
authenticated user may read it; it reveals no per-lab or per-user data.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep

router = APIRouter(prefix="/roles", tags=["roles"])


class RoleOut(BaseModel):
    name: str
    scopes: list[str]  # subset of {"global", "lab"}
    permissions: list[str]


@router.get("")
async def list_roles(_: CurrentUserDep) -> list[RoleOut]:
    return [
        RoleOut(
            name=name,
            scopes=sorted(spec.scopes),
            permissions=sorted(spec.permissions),
        )
        for name, spec in perms.ROLE_CATALOG.items()
    ]
