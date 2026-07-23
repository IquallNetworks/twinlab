import json
from collections.abc import Callable

import httpx
import pydantic
import pytest

from twinlab_backend.models import TestExpectation, TestSuite, ValidationTest
from twinlab_backend.services.clab_api import ClabApiClient
from twinlab_backend.services.validation import evaluate_expectation, run_suite

# --- The matcher (pure) ---


def test_contains_and_not_contains() -> None:
    assert evaluate_expectation("neighbor is Full", TestExpectation(contains="Full"))[0]
    assert not evaluate_expectation("neighbor is Init", TestExpectation(contains="Full"))[0]
    assert evaluate_expectation("no errors here", TestExpectation(not_contains="drop"))[0]
    assert not evaluate_expectation("1 drop", TestExpectation(not_contains="drop"))[0]


def test_matches_regex() -> None:
    assert evaluate_expectation("state: FULL/DR", TestExpectation(matches=r"FULL/\w+"))[0]
    assert not evaluate_expectation("state: 2WAY", TestExpectation(matches=r"FULL/\w+"))[0]


def test_json_path_equals() -> None:
    body = json.dumps({"neighbors": [{"state": "Full"}]})
    ok, _ = evaluate_expectation(
        body, TestExpectation(json_path="neighbors.0.state", equals="Full")
    )
    assert ok
    bad, _ = evaluate_expectation(
        body, TestExpectation(json_path="neighbors.0.state", equals="Init")
    )
    assert not bad


def test_json_path_errors_are_failures_not_crashes() -> None:
    # Invalid JSON, a missing key, and an out-of-range index each fail cleanly.
    assert not evaluate_expectation("not json", TestExpectation(json_path="a", equals=1))[0]
    assert not evaluate_expectation("{}", TestExpectation(json_path="a", equals=1))[0]
    assert not evaluate_expectation("[]", TestExpectation(json_path="0", equals=1))[0]


def test_expectation_requires_exactly_one_matcher() -> None:
    with pytest.raises(pydantic.ValidationError, match="exactly one of"):
        _ = TestExpectation()
    with pytest.raises(pydantic.ValidationError, match="exactly one of"):
        _ = TestExpectation(contains="a", matches="b")


def test_json_path_requires_equals() -> None:
    with pytest.raises(pydantic.ValidationError, match="json_path requires equals"):
        _ = TestExpectation(json_path="a")
    with pytest.raises(pydantic.ValidationError, match="only valid with json_path"):
        _ = TestExpectation(contains="a", equals=1)


def test_bad_regex_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError, match="not a valid regex"):
        _ = TestExpectation(matches="(")


# --- The runner (over a mocked clab-api) ---

_NODE = {
    "nodeName": "r1",
    "name": "clab-lab1-r1",
    "image": "vyos",
    "state": "running",
    "ipv4_address": "10.0.0.1/24",
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ClabApiClient:
    return ClabApiClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://clab.test",
        username="u",
        password="p",
    )


def _exec_stdout(stdout: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        if request.method == "GET" and request.url.path == "/api/v1/labs/lab1":
            return httpx.Response(200, json=[_NODE])
        if request.method == "POST" and request.url.path == "/api/v1/labs/lab1/exec":
            # exec keys the node by container name, not the short node name.
            assert request.url.params.get("nodeFilter") == "clab-lab1-r1"
            return httpx.Response(
                200,
                json={
                    "clab-lab1-r1": [
                        {"cmd": ["sh"], "return-code": 0, "stdout": stdout, "stderr": ""}
                    ]
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    return handler


async def test_run_suite_passes_when_expectation_holds() -> None:
    suite = TestSuite(
        tests={
            "adj": ValidationTest(
                nodes=["r1"], command="show", expect=TestExpectation(contains="Full")
            )
        }
    )
    report = await run_suite(_client(_exec_stdout("neighbor Full")), "lab1", "conv", suite)
    assert report.suite == "conv"
    assert (report.passed, report.failed, report.errored) == (1, 0, 0)
    assert report.ok
    assert report.results[0].status == "pass"


async def test_run_suite_fails_when_expectation_misses() -> None:
    suite = TestSuite(
        tests={
            "adj": ValidationTest(
                nodes=["r1"], command="show", expect=TestExpectation(contains="Full")
            )
        }
    )
    report = await run_suite(_client(_exec_stdout("neighbor Init")), "lab1", "conv", suite)
    assert (report.passed, report.failed) == (0, 1)
    assert not report.ok
    assert report.results[0].status == "fail"


async def test_run_suite_errors_when_node_absent() -> None:
    # r2 isn't in the live lab (inspect returns only r1) -> error, not fail.
    suite = TestSuite(
        tests={
            "adj": ValidationTest(
                nodes=["r2"], command="show", expect=TestExpectation(contains="Full")
            )
        }
    )
    report = await run_suite(_client(_exec_stdout("irrelevant")), "lab1", "conv", suite)
    assert (report.errored, report.passed, report.failed) == (1, 0, 0)
    assert report.results[0].status == "error"
    assert not report.ok
