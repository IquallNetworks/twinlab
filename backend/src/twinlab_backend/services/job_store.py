"""Persistence for async lab jobs.

Mirrors `lab_store`: DB access is the boundary, each mutating operation commits
itself and returns a typed result. The `jobs` partial unique index (one
`running` row per lab) is the operation mutex — `submit_job` simply INSERTs and
lets the constraint decide, so two concurrent submits serialize in the database
rather than in application code.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import bindparam, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import Job, Lab
from twinlab_backend.services import lab_store

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# Finished jobs kept per lab (recent history, not an audit log); pruned at
# submit so the table can't grow unbounded on a busy lab.
KEEP_FINISHED = 20


@dataclass(frozen=True, slots=True)
class JobStoreError:
    reason: str  # "job_in_flight" | "not_found"
    detail: str = ""


async def submit_job(
    session: AsyncSession,
    lab_id: uuid.UUID,
    kind: str,
    request: dict[str, object],
    created_by: uuid.UUID | None,
) -> Job | JobStoreError:
    """Insert the running job row — which IS taking the lab's operation mutex.
    `job_in_flight` when another job on this lab is still running (the partial
    unique index rejected the INSERT)."""
    job = Job(
        lab_id=lab_id, kind=kind, status=STATUS_RUNNING, request=request, created_by=created_by
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # The only unique constraint an INSERT can trip here is the
        # one-running-per-lab index (labs are never hard-deleted, users are
        # SET NULL), so no disambiguation query is needed.
        return JobStoreError("job_in_flight", str(lab_id))
    # `created_at` is a server default: load it now, in this async context,
    # so rendering the fresh row can't trip a sync lazy-load.
    await session.refresh(job)
    return job


async def finish_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    result: dict[str, object] | None,
    error: dict[str, object] | None,
) -> Job | JobStoreError:
    """Record a job's terminal state: `succeeded` with its result payload, or
    `failed` with the error envelope. Exactly one of result/error is set by the
    caller (the job runner)."""
    job = await session.get(Job, job_id)
    if job is None:
        return JobStoreError("not_found", str(job_id))
    job.status = STATUS_FAILED if error is not None else STATUS_SUCCEEDED
    job.result = result
    job.error = error
    job.finished_at = datetime.now(UTC)
    await session.commit()
    return job


async def append_step(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    code: str,
    level: str,
    message: str,
) -> None:
    """Append one step to a running job's log (contract delta 29).

    An atomic `steps = steps || <step>` rather than read-modify-write: the job
    task holds a long-lived session mid-operation, and a step has to commit —
    and become pollable — the moment it happens without joining whatever
    transaction that operation is in the middle of. Hence the caller passes a
    session of its own (see `api.jobs.JobStepRecorder`).

    Silently a no-op for an unknown job id: the row is pruned or deleted only
    once the job is long finished, and there is nothing to salvage.
    """
    step: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
        "code": code,
        "level": level,
        "message": message,
    }
    # `steps || '[step]'::jsonb` — the append happens in the database, so two
    # writers could never lose one another's step (one job task writes today,
    # but a read-modify-write would be a trap waiting for the second).
    _ = await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(steps=Job.steps.concat(bindparam("step", [step], type_=JSONB)))
    )
    await session.commit()


async def get_job(session: AsyncSession, lab_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    """Fetch one job, scoped to the lab so a job id can't be read through
    another lab's URL."""
    return await session.scalar(select(Job).where(Job.id == job_id, Job.lab_id == lab_id))


async def list_jobs(session: AsyncSession, lab_id: uuid.UUID, *, limit: int) -> list[Job]:
    """A lab's recent jobs, newest first. UUIDv7 ids are time-ordered, so the id
    is a stable tiebreaker for rows created in the same clock tick."""
    stmt = (
        select(Job)
        .where(Job.lab_id == lab_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def list_recent_jobs(
    session: AsyncSession, *, lab_ids: set[uuid.UUID] | None, limit: int
) -> list[tuple[Job, str]]:
    """Recent jobs ACROSS labs, newest first, each paired with its lab's name
    (the caller renders `lab_name` and has no lab in hand).

    `lab_ids=None` means "every lab" — a caller holding lab:read globally;
    an empty set means the caller can read none, which is an empty list, not
    everything. Jobs of removed labs are excluded, so this list follows the
    lab listing: a destroy-with-remove job leaves when its record does."""
    if lab_ids is not None and not lab_ids:
        return []
    stmt = (
        select(Job, Lab.name)
        .join(Lab, Job.lab_id == Lab.id)
        .where(Lab.deleted_at.is_(None))
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit)
    )
    if lab_ids is not None:
        stmt = stmt.where(Job.lab_id.in_(lab_ids))
    rows = (await session.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def prune_finished(
    session: AsyncSession, lab_id: uuid.UUID, *, keep: int = KEEP_FINISHED
) -> None:
    """Drop a lab's finished jobs beyond the newest `keep`. Never touches a
    `running` row (the freshly inserted mutex holder included)."""
    keepers = (
        select(Job.id)
        .where(Job.lab_id == lab_id, Job.status != STATUS_RUNNING)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(keep)
    )
    _ = await session.execute(
        delete(Job).where(
            Job.lab_id == lab_id, Job.status != STATUS_RUNNING, Job.id.not_in(keepers)
        )
    )
    await session.commit()


async def fail_running(session: AsyncSession, *, code: str, message: str) -> list[Job]:
    """Sweep every `running` job to `failed` with the given envelope code. Run at
    startup (orphans from a crash/restart — the in-process task died with the
    process) and at shutdown (tasks just cancelled). Returns the swept jobs so
    the caller can restore lab state (a deploy job's `_previous_status`)."""
    running = list((await session.scalars(select(Job).where(Job.status == STATUS_RUNNING))).all())
    now = datetime.now(UTC)
    for job in running:
        job.status = STATUS_FAILED
        job.error = {"status_code": 502, "code": code, "message": message, "extras": {}}
        job.finished_at = now
    await session.commit()
    return running


async def sweep_orphans(session: AsyncSession, *, code: str, message: str) -> list[Job]:
    """Fail every `running` job AND undo their side effects on lab state: a
    deploy job orphaned mid-flight leaves its lab wedged at `deploying`, so
    restore the pre-deploy status stashed in the job's request. Run at startup
    (backend_restart) and shutdown (backend_shutdown) — single-process
    assumption: any `running` row belongs to THIS process's dead tasks."""
    swept = await fail_running(session, code=code, message=message)
    for job in swept:
        if job.kind != "deploy":
            continue
        previous = job.request.get("_previous_status")
        if not isinstance(previous, str):
            continue
        lab = await session.get(Lab, job.lab_id)
        # Only unwedge a lab still parked at `deploying`; a deploy that got as
        # far as mark_deployed left a truthful status behind.
        if lab is not None and lab.status == lab_store.STATUS_DEPLOYING:
            lab.status = previous
    await session.commit()
    return swept
