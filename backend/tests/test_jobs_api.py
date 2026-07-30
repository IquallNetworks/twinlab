"""Job machinery unit tests: the run_job boundary adapter, job_out mapping and
the job-event fan-out.

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
from twinlab_backend.services.job_events import JobEventBroker

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

    await run_job(_factory(), uuid.uuid7(), work, events=JobEventBroker(), lab_name="tmp1")
    assert finish.calls == 1
    assert finish.result == {"status": "deployed"}
    assert finish.error is None


async def test_run_job_maps_api_error_to_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    finish = _Finish()
    monkeypatch.setattr(jobs_api.job_store, "finish_job", finish)

    async def work() -> _Payload:
        raise ApiError(422, "netlab_invalid", "bad definition", {"stderr": "boom"})

    await run_job(_factory(), uuid.uuid7(), work, events=JobEventBroker(), lab_name="tmp1")
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

    await run_job(_factory(), uuid.uuid7(), work, events=JobEventBroker(), lab_name="tmp1")
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


async def test_run_job_publishes_the_terminal_event(monkeypatch: pytest.MonkeyPatch) -> None:
    # The whole point of delta 16: a watcher learns the job finished without
    # polling for it. The event announces the row that was WRITTEN.
    finish = _Finish()
    monkeypatch.setattr(jobs_api.job_store, "finish_job", finish)
    broker = JobEventBroker()

    async def work() -> _Payload:
        return _Payload()

    with broker.subscribe() as queue:
        await run_job(_factory(), uuid.uuid7(), work, events=broker, lab_name="tmp1")
        event = queue.get_nowait()
    assert event.lab == "tmp1"
    assert event.status == "succeeded"
    assert event.kind == "deploy"
    assert queue.empty()


async def test_run_job_publishes_nothing_when_the_row_vanished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def gone(
        session: object,
        job_id: uuid.UUID,
        *,
        result: dict[str, object] | None,
        error: dict[str, object] | None,
    ) -> job_store.JobStoreError:
        return job_store.JobStoreError("not_found", str(job_id))

    monkeypatch.setattr(jobs_api.job_store, "finish_job", gone)
    broker = JobEventBroker()

    async def work() -> _Payload:
        return _Payload()

    with broker.subscribe() as queue:
        await run_job(_factory(), uuid.uuid7(), work, events=broker, lab_name="tmp1")
        assert queue.empty()


def test_job_event_timestamp_follows_the_row() -> None:
    running = _job()
    assert jobs_api.job_event(running, "tmp1").timestamp == _TS
    done = _job(status="succeeded")
    done.finished_at = datetime(2026, 7, 29, 12, 5, tzinfo=UTC)
    assert jobs_api.job_event(done, "tmp1").timestamp == done.finished_at


def test_broker_fans_out_and_unsubscribes() -> None:
    broker = JobEventBroker()
    event = jobs_api.job_event(_job(), "tmp1")
    with broker.subscribe() as first, broker.subscribe() as second:
        broker.publish(event)
        assert first.get_nowait() == event
        assert second.get_nowait() == event
    # Both queues left the subscriber set on exit: a publish to nobody is a
    # no-op, not an error — jobs must not care whether anyone is watching.
    broker.publish(event)
    assert first.empty()


def test_broker_drops_instead_of_blocking_a_full_subscriber() -> None:
    # A stream that stopped reading must not stall the job runner.
    broker = JobEventBroker()
    event = jobs_api.job_event(_job(), "tmp1")
    with broker.subscribe() as queue:
        for _ in range(queue.maxsize + 5):
            broker.publish(event)
        assert queue.qsize() == queue.maxsize


async def test_list_recent_jobs_empty_readable_set_is_empty() -> None:
    # An empty set means "reads no lab" — it must never widen to "every lab"
    # (an `IN ()` would be a silent full scan). Short-circuits before any DB use.
    rows = await job_store.list_recent_jobs(cast("AsyncSession", object()), lab_ids=set(), limit=20)
    assert rows == []


def test_fail_running_status_constants_cover_check_constraint() -> None:
    # The ORM CHECK constraints and the store constants must agree, or an
    # insert/sweep would violate them at runtime.
    assert {job_store.STATUS_RUNNING, job_store.STATUS_SUCCEEDED, job_store.STATUS_FAILED} == {
        "running",
        "succeeded",
        "failed",
    }
