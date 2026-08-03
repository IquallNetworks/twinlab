"""Persistence for durable lab records.

The definition is a lab's source of truth, so it is stored on deploy and reused
on configure (the caller never resupplies it). DB access is the boundary; each
mutating operation commits itself and returns a typed result so the HTTP layer
can map it to a status code. Genuine infrastructure failures (a dead connection)
raise — only domain outcomes are values.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import Job, Lab

# Status values a lab row can hold (the lifecycle split). "created" is a bare
# record (no definition yet); "deploying" is a deploy job in flight (display
# only — the jobs table's partial unique index is the actual mutex).
STATUS_CREATED = "created"
STATUS_DEPLOYING = "deploying"
STATUS_DEPLOYED = "deployed"
STATUS_DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class LabStoreError:
    reason: str  # "not_found" | "subnet_taken" | "name_taken"
    detail: str = ""


async def get_lab(session: AsyncSession, name: str, *, include_deleted: bool = False) -> Lab | None:
    """Fetch a lab by name. Soft-deleted rows are hidden by default so every read
    endpoint that resolves a lab treats a deleted one as absent (404). Internal
    machinery that must find the row regardless of state (reservation, which
    revives a deleted name on redeploy) passes `include_deleted=True`."""
    stmt = select(Lab).where(Lab.name == name)
    if not include_deleted:
        stmt = stmt.where(Lab.deleted_at.is_(None))
    return await session.scalar(stmt)


async def list_labs(session: AsyncSession) -> list[Lab]:
    """The active catalog: soft-deleted labs are excluded."""
    return list(
        (
            await session.scalars(select(Lab).where(Lab.deleted_at.is_(None)).order_by(Lab.name))
        ).all()
    )


async def used_mgmt_subnets(session: AsyncSession) -> set[str]:
    """Every management subnet currently assigned to a lab record, any status.
    Soft-deleted rows released theirs (set NULL on delete), so no filter is
    needed here."""
    rows = await session.scalars(select(Lab.mgmt_subnet).where(Lab.mgmt_subnet.is_not(None)))
    return {subnet for subnet in rows.all() if subnet is not None}


async def create_lab(
    session: AsyncSession, name: str, mgmt_subnet: str, owner_id: uuid.UUID
) -> Lab | LabStoreError:
    """Create a bare lab record (the lifecycle split's cheap create): status
    `created`, no definition, mgmt subnet claimed atomically by the unique
    index. A previously soft-deleted name is revived as a FRESH record (its old
    definition/suites/templates cleared — deletion freed the name). `name_taken`
    when an active lab holds the name; `subnet_taken` when another lab holds
    this subnet (the caller re-allocates and retries)."""
    existing = await get_lab(session, name, include_deleted=True)
    if existing is not None and existing.deleted_at is None:
        return LabStoreError("name_taken", name)
    if existing is None:
        lab = Lab(
            name=name,
            status=STATUS_CREATED,
            created_by=owner_id,
            owner_id=owner_id,
            mgmt_subnet=mgmt_subnet,
        )
        session.add(lab)
    else:
        lab = existing
        lab.definition = None
        lab.status = STATUS_CREATED
        lab.created_by = owner_id
        lab.owner_id = owner_id
        lab.mgmt_subnet = mgmt_subnet
        lab.test_suites = None
        lab.last_validation = None
        lab.config_time_ok = None
        lab.custom_config = None
        lab.links = None
        lab.node_facts = None
        # A leaked claim (destroy-time bridge cleanup failed, then the name was
        # removed and recreated) is dropped with the rest of the old record:
        # the fresh lab's own deploys re-ensure idempotently and its destroy
        # deletes the same names, so the leak self-heals on next use.
        lab.host_bridges = None
        lab.deleted_at = None
        # A revived name starts with NO job history — the row keeps its id, so
        # without this the previous incarnation's jobs (possibly a different
        # owner's results) would surface on the fresh lab.
        _ = await session.execute(delete(Job).where(Job.lab_id == lab.id))
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
    # The revive path UPDATEs the row, so server-side `updated_at` (onupdate) is
    # expired; load it here, in this async context, so rendering the record
    # can't trip a sync lazy-load. (The insert path gets values via RETURNING.)
    await session.refresh(lab)
    return lab


async def set_status(session: AsyncSession, name: str, status: str) -> Lab | LabStoreError:
    """Set a lab's display status (`deploying` while a deploy job runs; a failed
    deploy restores the previous value). Plain — the job row is the mutex."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.status = status
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


async def soft_delete(session: AsyncSession, name: str) -> Lab | LabStoreError:
    """Mark a lab deleted: hidden from list/detail and inoperable, the row kept
    for audit. RELEASES the mgmt subnet (contract delta 11) — a deleted record
    can't be redeployed through the API, so holding its /24 would only walk the
    pool toward exhaustion. `not_found` when the lab is absent or already
    deleted. Creating the same name later revives the row as a fresh record
    (see `create_lab`)."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.deleted_at = datetime.now(UTC)
    lab.mgmt_subnet = None
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


async def update_custom_config(
    session: AsyncSession, name: str, custom_config: dict[str, object]
) -> Lab | LabStoreError:
    """Replace a lab's user-defined custom-config templates. The caller has
    validated the paths and checked them against the built-in namespace; here we
    only persist. `not_found` when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.custom_config = custom_config
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


async def set_links(
    session: AsyncSession, name: str, links: dict[str, object]
) -> Lab | LabStoreError:
    """Persist a lab's derived link table alone: the lazy backfill for rows
    predating the cache (GET regenerates from the stored definition) and the
    deploy-path refresh (deploy re-runs the same `netlab create`). `not_found`
    when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.links = links
    await session.commit()
    return lab


async def set_node_facts(
    session: AsyncSession, name: str, node_facts: dict[str, object]
) -> Lab | LabStoreError:
    """Persist a lab's derived fact namespace alone — same lifecycle as
    `set_links`: lazy backfill for rows predating the cache and the
    deploy-path refresh. `not_found` when the lab was never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.node_facts = node_facts
    await session.commit()
    return lab


async def set_host_bridges(
    session: AsyncSession, name: str, bridges: list[str] | None
) -> Lab | LabStoreError:
    """Persist a lab's host-bridge claim (the bridges its deploy created via
    the hostprep sidecar; None = none). Written BEFORE the clab deploy and
    released only when destroy confirms the bridges gone, so the record always
    lists what may exist on the host. Finds soft-deleted rows too: a claim can
    outlive removal (failed cleanup) and must stay visible to the collision
    check until released."""
    lab = await get_lab(session, name, include_deleted=True)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.host_bridges = bridges
    await session.commit()
    return lab


async def bridge_owners(session: AsyncSession, exclude_lab: str) -> dict[str, str]:
    """bridge name -> owning lab name, over every OTHER lab currently claiming
    host bridges. Bridge names truncate the lab name to 10 characters, so two
    labs can collide on them; the deploy path uses this to refuse loudly where
    netlab itself would silently cross-wire two labs' segments. Soft-deleted
    rows are INCLUDED: a claim that outlived removal still describes bridges
    on the host."""
    rows = await session.scalars(
        select(Lab).where(Lab.host_bridges.is_not(None), Lab.name != exclude_lab)
    )
    return {bridge: lab.name for lab in rows.all() for bridge in (lab.host_bridges or [])}


async def transfer_owner(
    session: AsyncSession, name: str, new_owner_id: uuid.UUID
) -> Lab | LabStoreError:
    """Reassign a lab's owner. The caller validates the new owner exists and is
    authorized to transfer; here we only persist. `not_found` when the lab is
    absent."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.owner_id = new_owner_id
    await session.commit()
    return lab


async def update_definition(
    session: AsyncSession,
    name: str,
    definition: str,
    mgmt_subnet: str,
    links: dict[str, object],
    node_facts: dict[str, object],
) -> Lab | LabStoreError:
    """Replace a lab's stored definition without touching its runtime. The caller
    validates the definition (and pins the lab's name and mgmt subnet into it)
    first; here we only persist. `links` and `node_facts` are the definition's
    derived link table (serialized {"links": [...]}) and fact namespace, both
    byproducts of the validating `netlab create` — stored together so the caches
    can never describe a different definition. `not_found` when the lab was
    never recorded here."""
    lab = await get_lab(session, name)
    if lab is None:
        return LabStoreError("not_found", name)
    lab.definition = definition
    lab.mgmt_subnet = mgmt_subnet
    lab.links = links
    lab.node_facts = node_facts
    try:
        await session.commit()
    except IntegrityError:
        # An explicit mgmt subnet in the edited definition collides with another
        # lab's; surface it rather than persisting a definition that can't deploy.
        await session.rollback()
        return LabStoreError("subnet_taken", mgmt_subnet)
    return lab
