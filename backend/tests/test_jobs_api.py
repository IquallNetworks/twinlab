"""Job machinery unit tests: the run_job boundary adapter and job_out mapping.

DB-less like the rest of the suite: run_job's finish write is intercepted by
monkeypatching job_store.finish_job (the session factory hands out a dummy).
"""

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import cast

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twinlab_backend.api import jobs as jobs_api
from twinlab_backend.api.jobs import job_out, run_job
from twinlab_backend.api_errors import ApiError
from twinlab_backend.db.models import Job
from twinlab_backend.services import job_store

_TS = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _job(
    kind: str = "deploy",
    status: str = "running",
    request: dict[str, object] | None = None,
    error: dict[str, object] | None = None,
) -> Job:
    job = Job(kind=kind, status=status, request=request or {}, error=error)
    # ids/timestamps fill on flush; set explicitly for the unsaved instance.
    job.id = uuid.uuid7()
    job.lab_id = uuid.uuid7()
    job.created_at = _TS
    return job


class _NullSession:
    """Stands in for an AsyncSession context: run_job only passes it through to
    the (monkeypatched) finish_job."""

    async def __aenter__(self) -> _NullSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


def _factory() -> async_sessionmaker[AsyncSession]:
    return cast("async_sessionmaker[AsyncSession]", _NullSession)


class _Payload(BaseModel):
    status: str = "deployed"


class _Finish:
    """Captures finish_job's terminal write."""

    def __init__(self) -> None:
        self.result: dict[str, object] | None = None
        self.error: dict[str, object] | None = None
        self.calls = 0

    async def __call__(
        self,
        session: object,
        job_id: uuid.UUID,
        *,
        result: dict[str, object] | None,
        error: dict[str, object] | None,
    ) -> Job:
        self.calls += 1
        self.result = result
        self.error = error
        return _job(status="failed" if error is not None else "succeeded")


async def test_run_job_success_stores_result(monkeypatch: pytest.MonkeyPatch) -> None:
    finish = _Finish()
    monkeypatch.setattr(jobs_api.job_store, "finish_job", finish)

    async def work() -> _Payload:
        return _Payload()

    await run_job(_factory(), uuid.uuid7(), work)
    assert finish.calls == 1
    assert finish.result == {"status": "deployed"}
    assert finish.error is None


async def test_run_job_maps_api_error_to_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    finish = _Finish()
    monkeypatch.setattr(jobs_api.job_store, "finish_job", finish)

    async def work() -> _Payload:
        raise ApiError(422, "netlab_invalid", "bad definition", {"stderr": "boom"})

    await run_job(_factory(), uuid.uuid7(), work)
    assert finish.result is None
    assert finish.error == {
        "status_code": 422,
        "code": "netlab_invalid",
        "message": "bad definition",
        "extras": {"stderr": "boom"},
    }


async def test_run_job_unexpected_exception_is_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The 500-handler analogue: an unforeseen crash must still finish the job —
    # a wedged `running` row would otherwise hold the lab's mutex forever.
    finish = _Finish()
    monkeypatch.setattr(jobs_api.job_store, "finish_job", finish)

    async def work() -> _Payload:
        raise RuntimeError("unexpected")

    await run_job(_factory(), uuid.uuid7(), work)
    assert finish.error is not None
    assert finish.error["code"] == "internal_error"
    assert finish.error["status_code"] == 500


def test_job_out_strips_private_request_keys() -> None:
    job = _job(request={"configure": True, "_previous_status": "destroyed"})
    out = job_out(job, "tmp1")
    assert out.request == {"configure": True}
    assert out.lab_name == "tmp1"
    assert out.kind == "deploy"
    assert out.status == "running"
    assert out.result is None and out.error is None


def test_job_out_parses_error_envelope() -> None:
    envelope: dict[str, object] = {
        "status_code": 502,
        "code": "upstream_error",
        "message": "clab-api unreachable",
        "extras": {},
    }
    job = _job(status="failed", error=envelope)
    out = job_out(job, "tmp1")
    assert out.error is not None
    assert out.error.code == "upstream_error"
    assert out.error.status_code == 502


def test_job_out_invalid_kind_is_loud() -> None:
    with pytest.raises(ApiError) as excinfo:
        _ = job_out(_job(kind="bb-nonsense"), "tmp1")
    assert excinfo.value.status_code == 500


def test_fail_running_status_constants_cover_check_constraint() -> None:
    # The ORM CHECK constraints and the store constants must agree, or an
    # insert/sweep would violate them at runtime.
    assert {job_store.STATUS_RUNNING, job_store.STATUS_SUCCEEDED, job_store.STATUS_FAILED} == {
        "running",
        "succeeded",
        "failed",
    }
