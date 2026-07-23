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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import Lab

# Status values a lab row can hold. "deploying" is a transient reservation state
# held while a deploy is in flight (so its mgmt subnet is claimed atomically
# before the slow deploy runs). "stored" (saved but never deployed) is reserved
# for a future save-only flow.
STATUS_DEPLOYING = "deploying"
STATUS_DEPLOYED = "deployed"
STATUS_DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class LabStoreError:
    reason: str  # "not_found" | "subnet_taken" | "name_taken"
    detail: str = ""


async def get_lab(session: AsyncSession, name: str) -> Lab | None:
    return await session.scalar(select(Lab).where(Lab.name == name))


async def list_labs(session: AsyncSession) -> list[Lab]:
    return list((await session.scalars(select(Lab).order_by(Lab.name))).all())


async def used_mgmt_subnets(session: AsyncSession) -> set[str]:
    """Every management subnet currently assigned to a lab record, any status.
    Records are never hard-deleted, so this is the full set to avoid when
    allocating a new lab's subnet."""
    rows = await session.scalars(select(Lab.mgmt_subnet).where(Lab.mgmt_subnet.is_not(None)))
    return {subnet for subnet in rows.all() if subnet is not None}


async def reserve_lab(
    session: AsyncSession, name: str, definition: str, mgmt_subnet: str, owner_id: uuid.UUID
) -> Lab | LabStoreError:
    """Claim a lab's row and mgmt subnet BEFORE the (slow) deploy, so two
    concurrent deploys can't grab the same /24. Creates the row (`deploying`) or
    re-arms a previously destroyed one. `subnet_taken` when another lab already
    holds this subnet (the unique index rejects the commit); `name_taken` when the
    name was claimed concurrently — the caller re-allocates or 409s accordingly."""
    lab = await get_lab(session, name)
    if lab is None:
        lab = Lab(
            name=name,
            definition=definition,
            status=STATUS_DEPLOYING,
            created_by=owner_id,
            mgmt_subnet=mgmt_subnet,
        )
        session.add(lab)
    else:
        lab.definition = definition
        lab.status = STATUS_DEPLOYING
        lab.created_by = owner_id
        lab.mgmt_subnet = mgmt_subnet
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Which unique constraint fired? If another lab now holds this subnet it's
        # subnet contention (retry with a fresh one); otherwise the name raced.
        holder = await session.scalar(
            select(Lab).where(Lab.mgmt_subnet == mgmt_subnet, Lab.name != name)
        )
        if holder is not None:
            return LabStoreError("subnet_taken", mgmt_subnet)
        return LabStoreError("name_taken", name)
    return lab


async def release_reservation(session: AsyncSession, name: str, *, created_new: bool) -> None:
    """Undo a reservation after a failed deploy. A freshly-created reservation is
    deleted (freeing the name and its subnet); a re-armed destroyed lab reverts to
    `destroyed`, keeping its record."""
    lab = await get_lab(session, name)
    if lab is None:
        return
    if created_new:
        await session.delete(lab)
    else:
        lab.status = STATUS_DESTROYED
    await session.commit()


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
    """Flip a lab to `deployed` once its deploy succeeds — from `deploying` after
    a fresh deploy, or from `destroyed`/`deployed` on redeploy. Preserves the
    definition, owner, and mgmt subnet fixed at reservation. `not_found` when the
    lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.status = STATUS_DEPLOYED
    await session.commit()
    return lab


async def update_test_suites(
    session: AsyncSession, name: str, test_suites: dict[str, object]
) -> Lab | LabStoreError:
    """Replace a lab's stored test suites. The caller has validated them into the
    schema and serialized them; here we only persist. `not_found` when the lab was
    never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.test_suites = test_suites
    await session.commit()
    return lab


async def record_validation(
    session: AsyncSession,
    name: str,
    reports_by_suite: dict[str, object],
    *,
    config_time_ok: bool | None,
    set_config_time: bool,
) -> Lab | LabStoreError:
    """Persist the results of a validation run. `reports_by_suite` is merged into
    the stored per-suite results (so a single manual run updates just that suite).
    `set_config_time` gates the config-time flag: True for a config-time run (which
    records pass/fail), False for a manual run (which must not touch the gate).
    `not_found` when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    merged = dict(lab.last_validation or {})
    merged.update(reports_by_suite)
    lab.last_validation = merged  # reassign (not in-place) so the JSON column updates
    if set_config_time:
        lab.config_time_ok = config_time_ok
    await session.commit()
    return lab


async def update_definition(
    session: AsyncSession, name: str, definition: str, mgmt_subnet: str
) -> Lab | LabStoreError:
    """Replace a lab's stored definition without touching its runtime. The caller
    validates the definition (and pins the lab's name and mgmt subnet into it)
    first; here we only persist. `not_found` when the lab was never recorded
    here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.definition = definition
    lab.mgmt_subnet = mgmt_subnet
    try:
        await session.commit()
    except IntegrityError:
        # An explicit mgmt subnet in the edited definition collides with another
        # lab's; surface it rather than persisting a definition that can't deploy.
        await session.rollback()
        return LabStoreError("subnet_taken", mgmt_subnet)
    return lab
