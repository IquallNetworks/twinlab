"""Job-model contract WITHOUT deploys: submit/read/wait, hiding, history.

Cheap job sources on an undeployed lab:

- destroy-with-remove on a bare record — deterministic, fast, and the ONLY
  way to probe the "job stays pollable after the lab is soft-deleted" edge.
- a suite run with `wait: 0` — the execs error against absent nodes, but a
  suite that RAN is a succeeded job (results are data), terminal within
  seconds. Used wherever a job on a still-existing lab is needed.

Real deploy/configure jobs live in test_labs_deploy.py behind the marker.
"""

import uuid
from collections.abc import Callable

import pytest
from twinlab_client import (
    DestroyResponse,
    Job,
    SuiteReport,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    ValidationTest,
)

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

# Suite-run jobs on an undeployed lab only shell out per node; generous slack.
JOB_WAIT = 180.0

_TRIVIAL_SUITES = {
    "bb-jobs": TestSuite(
        tests={
            "probe": ValidationTest(
                nodes=["n1"],
                command="echo bb-probe",
                expect=TestExpectation(contains="bb-probe"),
                wait=0,
            )
        },
    )
}


async def _suite_run_job(admin: TwinlabClient, lab_name: str) -> Job:
    """Author the trivial suite and submit a run of it."""
    _ = await admin.update_definition(lab_name, LINUX_LAB_DEFINITION)
    _ = await admin.put_test_suites(lab_name, _TRIVIAL_SUITES)
    return await admin.run_test_suite(lab_name, "bb-jobs")


async def test_destroy_remove_job_stays_pollable_after_delete(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    lab = await admin.create_lab(unique("lab"))
    job = await admin.destroy_lab(lab.name, remove=True)
    assert job.kind == "destroy"
    assert job.lab_name == lab.name
    assert job.request == {"remove": True}

    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DestroyResponse)
    assert done.result.status == "deleted"
    assert done.finished_at is not None

    # The lab record is gone (existence-hiding 404) ...
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.get_lab(lab.name)
    assert excinfo.value.status_code == 404
    # ... but the job that removed it MUST stay readable — its terminal
    # state is only reachable this way (get and list both).
    again = await admin.get_job(lab.name, job.id)
    assert again.status == "succeeded"
    assert job.id in {j.id for j in await admin.list_jobs(lab.name)}


async def test_suite_run_job_reports_result(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    job = await _suite_run_job(admin, lab.name)
    assert job.kind == "suite_run"

    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    # The suite RAN (against absent nodes), so the job succeeds; the check
    # itself doesn't pass — as a transport error OR an expectation fail on
    # empty output (observed: netlab exec against an absent node succeeds
    # with no stdout). Either way it is data on the report, not a job failure.
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, SuiteReport)
    assert done.result.suite == "bb-jobs"
    assert done.result.passed == 0
    assert done.result.failed + done.result.errored >= 1


async def test_jobs_hidden_from_outsiders(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    job = await _suite_run_job(admin, lab.name)
    _, outsider = await make_user_client(None)

    # Existence-hiding on the job routes too: 404, never 403.
    with pytest.raises(TwinlabApiError) as get_exc:
        _ = await outsider.get_job(lab.name, job.id)
    assert get_exc.value.status_code == 404
    with pytest.raises(TwinlabApiError) as list_exc:
        _ = await outsider.list_jobs(lab.name)
    assert list_exc.value.status_code == 404

    # An unknown job id on a readable lab is a 404 as well.
    with pytest.raises(TwinlabApiError) as ghost_exc:
        _ = await admin.get_job(lab.name, uuid.uuid4())
    assert ghost_exc.value.status_code == 404

    # Drain so teardown's destroy isn't refused by a still-running job.
    _ = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)


async def test_job_list_is_newest_first(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    assert await admin.list_jobs(lab.name) == []

    first = await _suite_run_job(admin, lab.name)
    _ = await admin.wait_job(lab.name, first.id, timeout=JOB_WAIT)
    second = await admin.run_test_suite(lab.name, "bb-jobs")
    _ = await admin.wait_job(lab.name, second.id, timeout=JOB_WAIT)

    listed = await admin.list_jobs(lab.name)
    assert [job.id for job in listed[:2]] == [second.id, first.id]

    listed_one = await admin.list_jobs(lab.name, limit=1)
    assert [job.id for job in listed_one] == [second.id]


async def test_no_job_history_across_revival(admin: TwinlabClient, make_lab: LabFactory) -> None:
    # Re-creating a removed lab name revives the record — but never its job
    # history: jobs must not leak across incarnations (a previous owner's
    # results are not the new lab's business).
    lab = await make_lab(None)
    job = await admin.destroy_lab(lab.name, remove=True)
    _ = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)

    revived = await admin.create_lab(lab.name)  # same name; make_lab cleans it up
    assert revived.status == "created"
    assert await admin.list_jobs(lab.name) == []
