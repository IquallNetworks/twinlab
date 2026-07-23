"""Persistence for durable lab records.

The definition is a lab's source of truth, so it is stored on deploy and reused
on configure (the caller never resupplies it). DB access is the boundary; each
mutating operation commits itself and returns a typed result so the HTTP layer
can map it to a status code. Genuine infrastructure failures (a dead connection)
raise — only domain outcomes are values.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import Lab

# Status values a lab row can hold. "stored" (saved but never deployed) is
# reserved for a future save-only flow; the flows here only set the other two.
STATUS_DEPLOYED = "deployed"
STATUS_DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class LabStoreError:
    reason: str  # "not_found" | "already_deployed"
    detail: str = ""


async def get_lab(session: AsyncSession, name: str) -> Lab | None:
    return await session.scalar(select(Lab).where(Lab.name == name))


async def list_labs(session: AsyncSession) -> list[Lab]:
    return list((await session.scalars(select(Lab).order_by(Lab.name))).all())


async def save_deployed(
    session: AsyncSession, name: str, definition: str, owner_id: uuid.UUID
) -> Lab:
    """Record a just-deployed lab, creating the row or reactivating a previously
    destroyed one (same name → same durable record). The caller is responsible
    for rejecting a redeploy over a still-`deployed` lab (see `get_lab`); this
    upsert deliberately does not, so it stays race-free at the write."""
    lab = await get_lab(session, name)
    if lab is None:
        lab = Lab(name=name, definition=definition, status=STATUS_DEPLOYED, created_by=owner_id)
        session.add(lab)
    else:
        lab.definition = definition
        lab.status = STATUS_DEPLOYED
        lab.created_by = owner_id
    await session.commit()
    return lab


async def mark_destroyed(session: AsyncSession, name: str) -> Lab | LabStoreError:
    """Flip a lab to `destroyed`, retaining its definition. `not_found` when the
    lab was never recorded here (e.g. deployed out-of-band)."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.status = STATUS_DESTROYED
    await session.commit()
    return lab


async def mark_deployed(session: AsyncSession, name: str) -> Lab | LabStoreError:
    """Flip a lab back to `deployed` after a redeploy, preserving owner and the
    stored definition (unlike `save_deployed`, which records a fresh deploy and
    its owner). `not_found` when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.status = STATUS_DEPLOYED
    await session.commit()
    return lab


async def update_definition(
    session: AsyncSession, name: str, definition: str
) -> Lab | LabStoreError:
    """Replace a lab's stored definition without touching its runtime. The caller
    validates the definition (and pins the lab's name into it) first; here we only
    persist. `not_found` when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.definition = definition
    await session.commit()
    return lab
