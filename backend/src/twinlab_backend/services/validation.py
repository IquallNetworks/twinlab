"""Test-suite validation runner.

Twinlab's own validation — deliberately not `netlab validate` (see ROADMAP Phase
5): a suite's tests run over clab-api `exec` and match a command's stdout with a
small, safe primitive. Config-time suites run after a configure to gate "config
done"; runtime suites run on demand. The matcher (`evaluate_expectation`) is a
pure function so it is unit-tested directly; the runner reaches the lab only
through the injected clab-api client. Errors are values; the one boundary
`try`/`except` sits around JSON parsing of a command's output.
"""

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from typing import cast

from twinlab_backend.models import (
    SuiteReport,
    TestExpectation,
    TestResult,
    TestSuite,
    ValidationTest,
)
from twinlab_backend.result import Err
from twinlab_backend.services.clab_api import ClabApiClient

# Poll cadence while waiting for a test to converge: short enough to notice a
# just-formed adjacency promptly, slow enough not to hammer clab-api exec.
_POLL_INTERVAL_SECONDS = 2.0
# Cap echoed/persisted stdout so a chatty command can't bloat a stored report.
_MAX_OUTPUT_CHARS = 4000


def evaluate_expectation(stdout: str, expect: TestExpectation) -> tuple[bool, str]:
    """Evaluate an expectation against a command's stdout, returning
    `(passed, detail)`. Pure and total — the sole home of expectation semantics."""
    if expect.contains is not None:
        return (expect.contains in stdout, f"expected to contain {expect.contains!r}")
    if expect.not_contains is not None:
        return (
            expect.not_contains not in stdout,
            f"expected not to contain {expect.not_contains!r}",
        )
    if expect.matches is not None:
        return (
            re.search(expect.matches, stdout) is not None,
            f"expected to match /{expect.matches}/",
        )
    # json_path form; the schema guarantees json_path and equals travel together.
    return _match_json(stdout, expect.json_path or "", expect.equals)


def _match_json(
    stdout: str, path: str, expected: str | int | float | bool | None
) -> tuple[bool, str]:
    try:
        current: object = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return (False, f"stdout is not valid JSON: {exc}")
    for part in path.split("."):
        # cast narrows json.loads' Any-typed containers to object elements so the
        # walk is fully typed; JSON keys are always strings, values arbitrary.
        if isinstance(current, list):
            seq = cast(list[object], current)
            try:
                index = int(part)
            except ValueError:
                return (False, f"segment {part!r} is not a list index in json_path {path!r}")
            if not 0 <= index < len(seq):
                return (False, f"index {index} out of range in json_path {path!r}")
            current = seq[index]
        elif isinstance(current, dict):
            mapping = cast(dict[str, object], current)
            if part not in mapping:
                return (False, f"key {part!r} not found in json_path {path!r}")
            current = mapping[part]
        else:
            return (False, f"cannot descend into {type(current).__name__} at {part!r}")
    return (current == expected, f"expected json_path {path} == {expected!r}, got {current!r}")


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def _run_check(
    clab: ClabApiClient,
    lab_name: str,
    containers: dict[str, str],
    inspect_error: str | None,
    test_name: str,
    test: ValidationTest,
    node: str,
) -> TestResult:
    """Run one test on one node, polling until it passes or its `wait` window
    elapses. A node absent from the live lab, or an exec that never succeeds within
    the window, is an `error` (not a `fail`): the assertion couldn't be evaluated."""
    started = time.monotonic()
    container = containers.get(node)
    if container is None:
        detail = inspect_error or f"node '{node}' is not running in the lab"
        return TestResult(
            test=test_name,
            node=node,
            status="error",
            command=test.command,
            output="",
            detail=detail,
            elapsed_ms=_elapsed_ms(started),
        )
    deadline = started + test.wait
    while True:
        run = await clab.exec(lab_name, container, test.command)
        if isinstance(run, Err):
            if time.monotonic() < deadline:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue
            return TestResult(
                test=test_name,
                node=node,
                status="error",
                command=test.command,
                output="",
                detail=f"exec failed: {run.error.message}",
                elapsed_ms=_elapsed_ms(started),
            )
        passed, detail = evaluate_expectation(run.value.stdout, test.expect)
        if passed or time.monotonic() >= deadline:
            return TestResult(
                test=test_name,
                node=node,
                status="pass" if passed else "fail",
                command=test.command,
                output=run.value.stdout[:_MAX_OUTPUT_CHARS],
                detail=detail,
                elapsed_ms=_elapsed_ms(started),
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def run_suite(
    clab: ClabApiClient, lab_name: str, suite_name: str, suite: TestSuite
) -> SuiteReport:
    """Run every (test, node) in a suite and tally the outcomes. One live inspect
    resolves node -> container up front; if it fails, every check reports the
    inspect error rather than silently passing."""
    inspected = await clab.inspect(lab_name)
    if isinstance(inspected, Err):
        containers: dict[str, str] = {}
        inspect_error: str | None = inspected.error.message
    else:
        containers = {n.node_name: n.container_name for n in inspected.value}
        inspect_error = None

    results = [
        await _run_check(clab, lab_name, containers, inspect_error, test_name, test, node)
        for test_name, test in suite.tests.items()
        for node in test.nodes
    ]
    return SuiteReport(
        suite=suite_name,
        stage=suite.stage,
        passed=sum(r.status == "pass" for r in results),
        failed=sum(r.status == "fail" for r in results),
        skipped=sum(r.status == "skip" for r in results),
        errored=sum(r.status == "error" for r in results),
        ran_at=datetime.now(UTC),
        results=results,
    )


async def run_config_time_suites(
    clab: ClabApiClient, lab_name: str, suites: dict[str, TestSuite]
) -> list[SuiteReport]:
    """Run the `config-time` suites (in declaration order) — the automatic gate at
    the end of a configure. Runtime suites are left for on-demand runs."""
    return [
        await run_suite(clab, lab_name, name, suite)
        for name, suite in suites.items()
        if suite.stage == "config-time"
    ]
