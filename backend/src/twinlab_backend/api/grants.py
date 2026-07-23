"""Per-lab access delegation: role grants and ownership transfer.

A lab owner (or anyone holding `lab:grant` on the lab) binds lab-scoped roles to
users or groups on that lab. Two safety rules hold:

- **Role must be lab-bindable** — a global role can't be attached to one lab.
- **Anti-escalation** — the granted role's permissions must be a subset of the
  caller's own effective permissions on the lab, so no one can hand out access they
  don't themselves hold (e.g. a lab_manager, lacking `lab:destroy`, can't grant
  lab_owner).

Ownership transfer is stricter still: it needs the caller to be owner-equivalent
(hold the full owner permission set on the lab), since the new owner gains everything.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import require_lab
from twinlab_backend.auth.service import effective_permissions_for
from twinlab_backend.db.models import Group, Lab, RoleBinding, User
from twinlab_backend.deps import SessionDep
from twinlab_backend.services import lab_store, rbac_store

router = APIRouter(prefix="/labs", tags=["grants"])

LabName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]

# The caller, guaranteed to hold lab:grant on the {lab_name} lab.
GrantorDep = Annotated[User, Depends(require_lab(perms.LAB_GRANT))]


class GrantRequest(BaseModel):
    principal_type: Literal["user", "group"]
    principal_id: uuid.UUID
    role: str


class GrantOut(BaseModel):
    id: uuid.UUID
    principal_type: str
    principal_id: uuid.UUID
    principal_name: str | None  # resolved display name, None if the principal vanished
    role: str


class TransferOwnerRequest(BaseModel):
    user_id: uuid.UUID


async def _load_lab(db: SessionDep, lab_name: str) -> Lab:
    lab = await lab_store.get_lab(db, lab_name)
    if lab is None:  # require_lab already 404s on a missing lab; defensive.
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return lab


async def _principal_names(db: SessionDep, bindings: list[RoleBinding]) -> dict[uuid.UUID, str]:
    """Resolve display names for the principals of a set of bindings, one query per
    principal kind."""
    user_ids = {b.principal_id for b in bindings if b.principal_type == perms.PRINCIPAL_USER}
    group_ids = {b.principal_id for b in bindings if b.principal_type == perms.PRINCIPAL_GROUP}
    names: dict[uuid.UUID, str] = {}
    if user_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all():
            names[u.id] = u.username
    if group_ids:
        for g in (await db.scalars(select(Group).where(Group.id.in_(group_ids)))).all():
            names[g.id] = g.name
    return names


@router.get("/{lab_name}/grants")
async def list_grants(lab_name: LabName, db: SessionDep, _: GrantorDep) -> list[GrantOut]:
    lab = await _load_lab(db, lab_name)
    bindings = await rbac_store.list_lab_bindings(db, lab.id)
    names = await _principal_names(db, bindings)
    return [
        GrantOut(
            id=b.id,
            principal_type=b.principal_type,
            principal_id=b.principal_id,
            principal_name=names.get(b.principal_id),
            role=b.role_name,
        )
        for b in bindings
    ]


@router.post("/{lab_name}/grants", status_code=201)
async def create_grant(
    lab_name: LabName, body: GrantRequest, db: SessionDep, grantor: GrantorDep
) -> GrantOut:
    lab = await _load_lab(db, lab_name)
    if not perms.role_bindable_at(body.role, perms.SCOPE_LAB):
        raise HTTPException(
            status_code=422,
            detail={"stage": "grants", "message": f"'{body.role}' is not a lab-bindable role"},
        )
    # Anti-escalation: you can only grant what you hold on this lab.
    granted = await effective_permissions_for(db, grantor, lab)
    if not perms.role_permissions(body.role).issubset(granted):
        raise HTTPException(
            status_code=403,
            detail={
                "stage": "grants",
                "message": f"cannot grant '{body.role}': it exceeds your permissions on this lab",
            },
        )
    created = await rbac_store.create_binding(
        db,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        role_name=body.role,
        scope_type=perms.SCOPE_LAB,
        lab_id=lab.id,
        granted_by=grantor.id,
    )
    if isinstance(created, rbac_store.RbacStoreError):
        raise HTTPException(
            status_code=404,
            detail={"stage": "grants", "reason": created.reason, "message": created.detail},
        )
    names = await _principal_names(db, [created])
    return GrantOut(
        id=created.id,
        principal_type=created.principal_type,
        principal_id=created.principal_id,
        principal_name=names.get(created.principal_id),
        role=created.role_name,
    )


@router.delete("/{lab_name}/grants/{binding_id}", status_code=204)
async def delete_grant(
    lab_name: LabName, binding_id: uuid.UUID, db: SessionDep, _: GrantorDep
) -> None:
    lab = await _load_lab(db, lab_name)
    binding = await rbac_store.get_lab_binding(db, binding_id, lab.id)
    if binding is None:
        raise HTTPException(
            status_code=404, detail={"stage": "grants", "message": "grant not found"}
        )
    await rbac_store.delete_binding(db, binding)


@router.put("/{lab_name}/owner")
async def transfer_owner(
    lab_name: LabName, body: TransferOwnerRequest, db: SessionDep, grantor: GrantorDep
) -> GrantOut:
    lab = await _load_lab(db, lab_name)
    # Transfer hands the recipient the full owner set, so require the caller to be
    # owner-equivalent (hold that whole set on the lab) — stricter than lab:grant, and
    # consistent with the anti-escalation rule for granting lab_owner.
    granted = await effective_permissions_for(db, grantor, lab)
    if not perms.LAB_OWNER_PERMISSIONS.issubset(granted):
        raise HTTPException(
            status_code=403,
            detail={
                "stage": "grants",
                "message": "only an owner (or admin) can transfer ownership",
            },
        )
    new_owner = await db.get(User, body.user_id)
    if new_owner is None:
        raise HTTPException(
            status_code=404, detail={"stage": "grants", "message": "user not found"}
        )
    updated = await lab_store.transfer_owner(db, lab_name, body.user_id)
    if isinstance(updated, lab_store.LabStoreError):
        raise HTTPException(
            status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
        )
    return GrantOut(
        id=updated.id,
        principal_type=perms.PRINCIPAL_USER,
        principal_id=body.user_id,
        principal_name=new_owner.username,
        role="owner",
    )
