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

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import require_lab
from twinlab_backend.db.models import Job, Lab
from twinlab_backend.deps import SessionDep
from twinlab_backend.models import JobErrorOut, JobKind, JobOut, JobStatus
from twinlab_backend.services import job_store, lab_store

router = APIRouter(prefix="/labs", tags=["jobs"])

# Same tight charset as the labs router; declared here (not imported from
# api.labs) because api.labs imports from this module — never the reverse.
_LabNamePath = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]

type SessionFactory = async_sessionmaker[AsyncSession]
# A job's work: the operation coroutine, returning the response model that
# becomes the job's `result`. Raising ApiError fails the job with that envelope.
type JobWork = Callable[[], Awaitable[BaseModel]]


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


async def run_job(session_factory: SessionFactory, job_id: uuid.UUID, work: JobWork) -> None:
    """Drive one job to its terminal row. The try/except IS the boundary
    adapter (errors-as-values ends here, like the HTTP exception handlers):
    ApiError -> the envelope; any other exception -> internal_error, because an
    unexpected crash must still finish the job."""
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None
    try:
        outcome = await work()
    except asyncio.CancelledError:
        # Shutdown cancelled us: no DB write from a cancelled task — the
        # shutdown/startup sweep marks the row.
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
        _ = await job_store.finish_job(db, job_id, result=result, error=error)


def spawn_job(request: Request, job_id: uuid.UUID, work: JobWork) -> None:
    """Launch a submitted job's task and track it for shutdown."""
    session_factory: SessionFactory = request.app.state.session_factory
    tasks: dict[uuid.UUID, asyncio.Task[None]] = request.app.state.job_tasks
    task = asyncio.create_task(run_job(session_factory, job_id, work), name=f"job-{job_id}")
    tasks[job_id] = task
    task.add_done_callback(lambda done: _reap(tasks, job_id, done))


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


@router.get(
    "/{lab_name}/jobs/{job_id}",
    dependencies=[Depends(require_lab(perms.LAB_READ, include_deleted=True))],
)
async def get_job(lab_name: _LabNamePath, job_id: uuid.UUID, db: SessionDep) -> JobOut:
    # include_deleted: a destroy-with-remove job outlives its lab record and
    # must stay pollable to its terminal state. Unknown job ids 404 like
    # unknown labs (nothing to enumerate).
    lab = await _lab_any(db, lab_name)
    if isinstance(lab, ApiError):
        raise lab
    job = await job_store.get_job(db, lab.id, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", f"lab '{lab_name}' has no job {job_id}")
    return job_out(job, lab_name)


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
