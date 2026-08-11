"""Async job plumbing + read endpoints (contract delta 12).

A submit route pre-checks synchronously, inserts the running job row (the
partial unique index is the mutex), then hands the operation's coroutine to
`spawn_job`. `run_job` is the async analogue of the registered exception
handlers: the one boundary where a raised `ApiError` becomes the job's error
envelope instead of an HTTP response — a job must never wedge at `running`.

Jobs run in-process (`asyncio.create_task`) with the task registry on
`app.state.job_tasks`; single-process assumption (bare uvicorn, one worker) —
the startup/shutdown sweeps in `job_store.sweep_orphans` rely on it.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import CurrentUserDep, require_lab
from twinlab_backend.auth.service import permitted_lab_ids
from twinlab_backend.db.models import Job, Lab
from twinlab_backend.deps import SessionDep
from twinlab_backend.models import (
    JobDetailOut,
    JobErrorOut,
    JobEvent,
    JobKind,
    JobOut,
    JobStatus,
    JobStepLevel,
    JobStepOut,
)
from twinlab_backend.services import job_store, lab_store
from twinlab_backend.services.job_events import JobEventBroker

router = APIRouter(prefix="/labs", tags=["jobs"])
# The cross-lab listing is not under a lab, so it gets its own router.
fleet_router = APIRouter(prefix="/jobs", tags=["jobs"])

# Same tight charset as the labs router; declared here (not imported from
# api.labs) because api.labs imports from this module — never the reverse.
_LabNamePath = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]

type SessionFactory = async_sessionmaker[AsyncSession]
# A job's work: the operation coroutine, returning the response model that
# becomes the job's `result`. Raising ApiError fails the job with that envelope.
# It receives a step recorder (delta 29) — the job id lives here and never
# reached the operation bodies, so this hands them the one capability they need
# without handing them the row.
type JobWork = Callable[[JobStepRecorder], Awaitable[BaseModel]]

# Steps a single job may record before it stops appending. Nothing emits more
# than a dozen; the cap exists so a future loop cannot bloat the row.
MAX_STEPS = 64


class JobStepRecorder:
    """Appends one job's step log (contract delta 29).

    Opens its OWN short-lived session per step: the operation holds a
    long-lived session mid-transaction, and a step has to commit — and become
    pollable — the moment it happens, without joining whatever that operation
    is in the middle of.

    Failures are NOT caught. A step is an UPDATE on the row this task owns; if
    it fails the database is gone, and the operation writes lab status
    throughout and would fail at its next store call regardless. `run_job`'s
    total except turns that into a failed job — the same treatment every other
    store call inside a job already gets."""

    def __init__(self, session_factory: SessionFactory, job_id: uuid.UUID) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._count = 0

    async def record(self, code: str, message: str, *, level: JobStepLevel = "info") -> None:
        if self._count > MAX_STEPS:
            return
        self._count += 1
        if self._count > MAX_STEPS:
            code, message, level = "steps_truncated", f"stopped after {MAX_STEPS} steps", "warning"
        async with self._session_factory() as db:
            await job_store.append_step(db, self._job_id, code=code, level=level, message=message)


def _job_kind(kind: str) -> JobKind:
    match kind:
        case "deploy" | "configure" | "destroy" | "suite_run":
            return kind
        case _:
            raise ApiError(500, "internal_error", f"job has invalid kind {kind!r}")


def _job_status(status: str) -> JobStatus:
    match status:
        case "running" | "succeeded" | "failed":
            return status
        case _:
            raise ApiError(500, "internal_error", f"job has invalid status {status!r}")


def job_out(job: Job, lab_name: str) -> JobOut:
    # Underscore-prefixed request keys are private bookkeeping (a deploy job's
    # `_previous_status` for the restore/sweep), not part of the echoed params.
    return JobOut(
        id=job.id,
        lab_name=lab_name,
        kind=_job_kind(job.kind),
        status=_job_status(job.status),
        request={k: v for k, v in job.request.items() if not k.startswith("_")},
        result=job.result,
        error=None if job.error is None else JobErrorOut.model_validate(job.error),
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def job_detail_out(job: Job, lab_name: str) -> JobDetailOut:
    """`job_out` plus the step log — served only when a job is read on its own.
    Steps are validated on the way out rather than trusted: they are stored as
    free JSONB, so a row written by an older or hand-edited backend fails
    loudly here instead of reaching a client as a half-typed step."""
    return JobDetailOut(
        **job_out(job, lab_name).model_dump(),
        steps=[JobStepOut.model_validate(step) for step in job.steps],
    )


async def run_job(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    work: JobWork,
    *,
    events: JobEventBroker,
    lab_name: str,
) -> None:
    """Drive one job to its terminal row, then announce it (delta 16). The
    try/except IS the boundary adapter (errors-as-values ends here, like the
    HTTP exception handlers): ApiError -> the envelope; any other exception ->
    internal_error, because an unexpected crash must still finish the job."""
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None
    try:
        outcome = await work(JobStepRecorder(session_factory, job_id))
    except asyncio.CancelledError:
        # Shutdown cancelled us: no DB write from a cancelled task — the
        # shutdown/startup sweep marks the row. No event either: the stream
        # dies with the process, so there is nobody left to tell.
        raise
    except ApiError as exc:
        error = {
            "status_code": exc.status_code,
            "code": exc.code,
            "message": exc.message,
            "extras": exc.extras,
        }
    except Exception as exc:
        error = {"status_code": 500, "code": "internal_error", "message": str(exc), "extras": {}}
    else:
        result = outcome.model_dump(mode="json")
    async with session_factory() as db:
        finished = await job_store.finish_job(db, job_id, result=result, error=error)
    # Announce the row we actually wrote — never the outcome we assumed. If the
    # row vanished, there is no terminal state to report.
    if isinstance(finished, Job):
        events.publish(job_event(finished, lab_name))


def job_event(job: Job, lab_name: str) -> JobEvent:
    """The stream's view of a job row: which job changed, and to what. The
    timestamp is the row's own — created_at while running, finished_at once
    terminal — so an event and the record it announces agree."""
    return JobEvent(
        lab=lab_name,
        job_id=job.id,
        kind=_job_kind(job.kind),
        status=_job_status(job.status),
        timestamp=job.created_at if job.finished_at is None else job.finished_at,
    )


def spawn_job(request: Request, job: Job, lab_name: str, work: JobWork) -> None:
    """Launch a submitted job's task, track it for shutdown, and announce the
    submission so watchers learn about the job without polling for it."""
    session_factory: SessionFactory = request.app.state.session_factory
    tasks: dict[uuid.UUID, asyncio.Task[None]] = request.app.state.job_tasks
    events: JobEventBroker = request.app.state.job_events
    job_id = job.id
    task = asyncio.create_task(
        run_job(session_factory, job_id, work, events=events, lab_name=lab_name),
        name=f"job-{job_id}",
    )
    tasks[job_id] = task
    task.add_done_callback(lambda done: _reap(tasks, job_id, done))
    events.publish(job_event(job, lab_name))


def _reap(
    tasks: dict[uuid.UUID, asyncio.Task[None]], job_id: uuid.UUID, task: asyncio.Task[None]
) -> None:
    _ = tasks.pop(job_id, None)
    # run_job never raises (its except is total), so the only unretrieved
    # outcome is cancellation; retrieving silences the never-retrieved warning.
    if not task.cancelled():
        _ = task.exception()


async def _lab_any(db: AsyncSession, lab_name: str) -> Lab | ApiError:
    lab = await lab_store.get_lab(db, lab_name, include_deleted=True)
    if lab is None:
        return ApiError(404, "lab_not_found", f"unknown lab '{lab_name}'")
    return lab


@fleet_router.get("")
async def list_all_jobs(
    user: CurrentUserDep,
    db: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[JobOut]:
    """Recent jobs across every lab the caller may read (contract delta 15).

    Any authenticated user; the readable-lab filter is the events stream's,
    so an unreadable lab is invisible rather than 403 — there is nothing to
    hide behind here, the route names no lab."""
    readable = await permitted_lab_ids(db, user, perms.LAB_READ)
    rows = await job_store.list_recent_jobs(db, lab_ids=readable, limit=limit)
    return [job_out(job, lab_name) for job, lab_name in rows]


@router.get(
    "/{lab_name}/jobs/{job_id}",
    dependencies=[Depends(require_lab(perms.LAB_READ, include_deleted=True))],
)
async def get_job(lab_name: _LabNamePath, job_id: uuid.UUID, db: SessionDep) -> JobDetailOut:
    # include_deleted: a destroy-with-remove job outlives its lab record and
    # must stay pollable to its terminal state. Unknown job ids 404 like
    # unknown labs (nothing to enumerate).
    lab = await _lab_any(db, lab_name)
    if isinstance(lab, ApiError):
        raise lab
    job = await job_store.get_job(db, lab.id, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", f"lab '{lab_name}' has no job {job_id}")
    # The one job route that carries the step log (delta 29) — the lists stay
    # summaries.
    return job_detail_out(job, lab_name)


@router.get(
    "/{lab_name}/jobs",
    dependencies=[Depends(require_lab(perms.LAB_READ, include_deleted=True))],
)
async def list_jobs(lab_name: _LabNamePath, db: SessionDep, limit: int = 20) -> list[JobOut]:
    # Newest first; recent history only (pruned at submit, see job_store).
    lab = await _lab_any(db, lab_name)
    if isinstance(lab, ApiError):
        raise lab
    jobs = await job_store.list_jobs(db, lab.id, limit=limit)
    return [job_out(job, lab_name) for job in jobs]
