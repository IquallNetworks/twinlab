"""Test-suite validation runner.

Twinlab's own validation — deliberately not `netlab validate` (see ROADMAP Phase
5): a suite's tests run a command on a node and match its stdout with a small,
safe primitive. Config-time suites run after a configure to gate "config done";
runtime suites run on demand. The matcher (`evaluate_expectation`) is a pure
function so it is unit-tested directly; the runner reaches nodes only through an
injected `NodeExecutor`, so it stays agnostic to the CLI transport (today
`netlab exec`, which picks per-NOS docker/ssh). Errors are values; the one
boundary `try`/`except` sits around JSON parsing of a command's output.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

from twinlab_backend.models import (
    SuiteReport,
    TestExpectation,
    TestResult,
    TestSuite,
    ValidationTest,
)
from twinlab_backend.result import Err, Result

# A command transport: given (node, command), return the command's stdout, or a
# typed error string when it couldn't run. Injected so validation is agnostic to
# *how* a node's CLI is reached — today the netlab-runner's `netlab exec`.
type NodeExecutor = Callable[[str, str], Awaitable[Result[str, str]]]

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
    executor: NodeExecutor,
    test_name: str,
    test: ValidationTest,
    node: str,
) -> TestResult:
    """Run one test on one node, polling until it passes or its `wait` window
    elapses. An exec that never succeeds within the window (e.g. the node is down)
    is an `error` — the assertion couldn't be evaluated; a command that runs but
    whose output doesn't match is a `fail`."""
    started = time.monotonic()
    deadline = started + test.wait
    while True:
        run = await executor(node, test.command)
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
                detail=f"exec failed: {run.error}",
                elapsed_ms=_elapsed_ms(started),
            )
        passed, detail = evaluate_expectation(run.value, test.expect)
        if passed or time.monotonic() >= deadline:
            return TestResult(
                test=test_name,
                node=node,
                status="pass" if passed else "fail",
                command=test.command,
                output=run.value[:_MAX_OUTPUT_CHARS],
                detail=detail,
                elapsed_ms=_elapsed_ms(started),
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def run_suite(executor: NodeExecutor, suite_name: str, suite: TestSuite) -> SuiteReport:
    """Run every (test, node) in a suite and tally the outcomes. The executor
    resolves each node's transport (netlab exec), so no container/name resolution
    is needed here; a node that's down surfaces as a per-check `error`."""
    results = [
        await _run_check(executor, test_name, test, node)
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
    executor: NodeExecutor, suites: dict[str, TestSuite]
) -> list[SuiteReport]:
    """Run the `config-time` suites (in declaration order) — the automatic gate at
    the end of a configure. Runtime suites are left for on-demand runs."""
    return [
        await run_suite(executor, name, suite)
        for name, suite in suites.items()
        if suite.stage == "config-time"
    ]
