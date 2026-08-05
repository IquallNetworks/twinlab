"""Test-suite validation runner (contract delta 17): render → execute → parse
→ assert.

Twinlab's own validation — deliberately not `netlab validate` (see ROADMAP
item 15): every stage is declarative data, no user code. Commands and
expectation strings are Jinja2-rendered per node against the lab's fact
namespace (sandboxed + strict-undefined); execution goes through an injected
`NodeExecutor` (today the netlab-runner's `netlab exec`, per-NOS docker/ssh,
with an opt-in interactive channel); output optionally parses as JSON or
through TextFSM (ntc-templates overlaid by Twinlab-packaged templates); parsed
data is asserted with napalm-validate's `compare` grammar, raw stdout with the
safe primitive matchers. Errors are values; `try`/`except` sits only at the
jinja2/json/textfsm/napalm boundaries.
"""

import asyncio
import copy
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import jinja2
import jinja2.sandbox
from napalm.base import validate as napalm_validate
from napalm.base.exceptions import ValidationException
from textfsm import TextFSMError, clitable

from twinlab_backend.models import (
    SuiteReport,
    TestCase,
    TestExpectation,
    TestResult,
    TestSuite,
    ValidationTest,
)
from twinlab_backend.result import Err, Ok, Result

# A command transport: given (node, command, interactive), return the command's
# stdout, or a typed error string when it couldn't run. Injected so validation
# is agnostic to *how* a node's CLI is reached — today the netlab-runner's
# `netlab exec` (`interactive` asks for a persistent CLI channel where the
# node's transport is SSH; a no-op over docker exec).
type NodeExecutor = Callable[[str, str, bool], Awaitable[Result[str, str]]]

# The fact namespace templates render against: netlab's raw node dicts keyed by
# short node name (delta 17 — provisional/unpinned, see GET /labs/{name}/facts).
type NodeFacts = dict[str, dict[str, object]]

# Poll cadence while waiting for a test to converge: short enough to notice a
# just-formed adjacency promptly, slow enough not to hammer the exec transport.
_POLL_INTERVAL_SECONDS = 2.0
# Cap echoed/persisted stdout so a chatty command can't bloat a stored report.
_MAX_OUTPUT_CHARS = 4000

# netlab device -> TextFSM platform (the ntc-templates index key). Pinned to
# the supported set; parsing a device outside it is an authoring error, not a
# guess. iol/ioll2 run classic IOS — ntc's deepest platform; they stay mapped
# after IOL's 2026-08-05 licensing withdrawal because the map is a generic
# mechanism, not a support claim.
TEXTFSM_PLATFORMS: dict[str, str] = {
    "iol": "cisco_ios",
    "ioll2": "cisco_ios",
    "routeros7": "mikrotik_routeros",
    "vyos": "vyos",
    "linux": "linux",
}

# Template resolution order: Twinlab-packaged templates first (commands ntc
# lacks — e.g. cisco_ios `show mpls ldp neighbor`), then the ntc-templates
# library. Each directory carries its own CliTable index.
_TWINLAB_TEMPLATES_DIR = Path(__file__).parent / "textfsm_templates"


def _ntc_templates_dir() -> Path:
    import ntc_templates

    return Path(ntc_templates.__file__).parent / "templates"


# --------------------------------------------------------------------------- #
# Render — sandboxed Jinja2 over the fact namespace
# --------------------------------------------------------------------------- #


def _address_filter(value: object) -> str:
    """`address`: strip a CIDR's prefix length ("10.0.0.5/32" -> "10.0.0.5").
    The one filter the namespace ships — netlab facts carry addresses in CIDR
    form, commands want bare addresses."""
    return str(value).split("/", 1)[0]


def _jinja_environment() -> jinja2.sandbox.SandboxedEnvironment:
    # Sandboxed (suite templates are user data — no attribute escapes) and
    # strict (an undefined variable is an authoring error, never an empty
    # string silently baked into a command).
    env = jinja2.sandbox.SandboxedEnvironment(undefined=jinja2.StrictUndefined)
    env.filters["address"] = _address_filter
    return env


_ENV = _jinja_environment()


def check_template_syntax(template: str) -> str | None:
    """Parse-check one template string; the error message when invalid. The
    always-on half of PUT-time validation (dry-rendering needs facts)."""
    try:
        _ = _ENV.parse(template)
    except jinja2.TemplateSyntaxError as exc:
        return str(exc)
    return None


def render_template(template: str, node: str, facts: NodeFacts) -> Result[str, str]:
    """Render one template string for one executing node. Fast-path: most
    strings carry no template syntax at all."""
    if "{{" not in template and "{%" not in template:
        return Ok(template)
    context: dict[str, object] = {"node": facts.get(node, {}), "nodes": facts}
    try:
        return Ok(_ENV.from_string(template).render(context))
    except (jinja2.TemplateError, jinja2.UndefinedError) as exc:
        return Err(f"template render failed: {exc}")


def _render_compare_spec(spec: object, node: str, facts: NodeFacts) -> Result[object, str]:
    """Render every string in a compare spec — keys and values (a rendered KEY
    is how a spec addresses a fact-derived peer, e.g. a neighbor IP)."""
    if isinstance(spec, str):
        rendered = render_template(spec, node, facts)
        if isinstance(rendered, Err):
            return rendered
        return Ok(rendered.value)
    if isinstance(spec, dict):
        rendered_dict: dict[str, object] = {}
        for key, value in cast("dict[str, object]", spec).items():
            rendered_key = render_template(key, node, facts)
            if isinstance(rendered_key, Err):
                return rendered_key
            rendered_value = _render_compare_spec(value, node, facts)
            if isinstance(rendered_value, Err):
                return Err(rendered_value.error)
            rendered_dict[rendered_key.value] = rendered_value.value
        return Ok(rendered_dict)
    if isinstance(spec, list):
        rendered_list: list[object] = []
        for item in cast("list[object]", spec):
            rendered_item = _render_compare_spec(item, node, facts)
            if isinstance(rendered_item, Err):
                return Err(rendered_item.error)
            rendered_list.append(rendered_item.value)
        return Ok(rendered_list)
    return Ok(spec)


def render_expectation(
    expect: TestExpectation, node: str, facts: NodeFacts
) -> Result[TestExpectation, str]:
    """Render every templated string inside an expectation for one node."""
    if expect.compare is not None:
        rendered = _render_compare_spec(expect.compare, node, facts)
        if isinstance(rendered, Err):
            return Err(rendered.error)
        return Ok(expect.model_copy(update={"compare": rendered.value}))
    for field in ("contains", "not_contains", "matches"):
        value = getattr(expect, field)
        if value is not None:
            rendered_str = render_template(cast("str", value), node, facts)
            if isinstance(rendered_str, Err):
                return Err(rendered_str.error)
            return Ok(expect.model_copy(update={field: rendered_str.value}))
    return Ok(expect)  # unreachable per schema; total anyway


def _template_strings(case: TestCase) -> list[tuple[str, str]]:
    """Every (field label, template string) a case carries — the unit PUT-time
    checks iterate."""
    strings = [("command", case.command)]
    for field in ("contains", "not_contains", "matches"):
        value = cast("str | None", getattr(case.expect, field))
        if value is not None:
            strings.append((f"expect.{field}", value))
    if case.expect.compare is not None:
        _collect_spec_strings(case.expect.compare, "expect.compare", strings)
    return strings


def _collect_spec_strings(spec: object, label: str, out: list[tuple[str, str]]) -> None:
    if isinstance(spec, str):
        out.append((label, spec))
    elif isinstance(spec, dict):
        for key, value in cast("dict[str, object]", spec).items():
            out.append((label, key))
            _collect_spec_strings(value, f"{label}.{key}", out)
    elif isinstance(spec, list):
        for index, item in enumerate(cast("list[object]", spec)):
            _collect_spec_strings(item, f"{label}[{index}]", out)


def _test_cases(test: ValidationTest) -> dict[str, TestCase]:
    """A test's cases keyed by device; the shared-case form keys as "" (every
    device)."""
    if isinstance(test.run, TestCase):
        return {"": test.run}
    return dict(test.run)


def check_suite_templates(
    suites: dict[str, TestSuite], facts: NodeFacts | None
) -> list[dict[str, str]]:
    """PUT-time template validation: syntax-check every template string always,
    and dry-render each per target node when facts are available (a lab with a
    definition). Returns one {suite, test, field, error} entry per problem —
    the 422 `template_invalid` payload."""
    problems: list[dict[str, str]] = []
    for suite_name, suite in suites.items():
        for test_name, test in suite.tests.items():
            for device, case in _test_cases(test).items():
                where = f"run[{device}]" if device else "run"
                for field, template in _template_strings(case):
                    label = f"{where}.{field}"
                    syntax_error = check_template_syntax(template)
                    if syntax_error is not None:
                        problems.append(
                            {
                                "suite": suite_name,
                                "test": test_name,
                                "field": label,
                                "error": syntax_error,
                            }
                        )
                        continue
                    if facts is None:
                        continue
                    for node in test.nodes:
                        rendered = render_template(template, node, facts)
                        if isinstance(rendered, Err):
                            problems.append(
                                {
                                    "suite": suite_name,
                                    "test": test_name,
                                    "field": f"{label} (node {node})",
                                    "error": rendered.error,
                                }
                            )
                            break  # one report per field, not per node
    return problems


# --------------------------------------------------------------------------- #
# Parse — stdout to structured data
# --------------------------------------------------------------------------- #


def parse_output(case: TestCase, device: str, stdout: str) -> Result[object, str]:
    """Turn stdout into the data `compare` asserts on, per the case's declared
    parse mode. A miss is an error result upstream — never a silent raw
    fallback."""
    if case.parse == "json":
        try:
            return Ok(cast("object", json.loads(stdout)))
        except json.JSONDecodeError as exc:
            return Err(f"stdout is not valid JSON: {exc}")
    if case.parse == "textfsm":
        platform = TEXTFSM_PLATFORMS.get(device)
        if platform is None:
            return Err(f"no TextFSM platform mapping for device {device!r}")
        return _parse_textfsm(platform, case.command, stdout)
    return Ok(stdout)


def _parse_textfsm(platform: str, command: str, stdout: str) -> Result[object, str]:
    """Resolve a TextFSM template (Twinlab overlay first, then ntc-templates)
    and parse stdout into a list of lowercase-keyed records — the same shape
    ntc_templates.parse_output produces."""
    for template_dir in (_TWINLAB_TEMPLATES_DIR, _ntc_templates_dir()):
        table = clitable.CliTable("index", str(template_dir))
        attributes = {"Command": command, "Platform": platform}
        try:
            table.ParseCmd(stdout, attributes)
        except clitable.CliTableError:
            continue  # no template in this directory; try the next
        except TextFSMError as exc:
            # The template resolved but the output does not fit it — a real
            # mismatch (a template written for another NOS release is the usual
            # cause). It is a typed error, not an exception to propagate: the
            # caller turns this into ONE `error` check, whereas an escaping
            # exception would fail the whole suite run.
            return Err(f"TextFSM template for {command!r} does not fit the output: {exc}")
        header = [str(name).lower() for name in table.header]
        return Ok([dict(zip(header, row, strict=True)) for row in table])
    return Err(f"no TextFSM template for platform {platform!r}, command {command!r}")


# --------------------------------------------------------------------------- #
# Assert — the matchers
# --------------------------------------------------------------------------- #


def evaluate_expectation(
    output: object, expect: TestExpectation
) -> tuple[bool, str, dict[str, object] | None]:
    """Evaluate a (rendered) expectation against a command's (parsed) output,
    returning `(passed, detail, diff)`. The sole home of matcher semantics;
    `diff` is napalm's structured report, only for the compare form."""
    if expect.compare is not None:
        return _evaluate_compare(output, expect.compare)
    stdout = output if isinstance(output, str) else json.dumps(output)
    if expect.contains is not None:
        return (expect.contains in stdout, f"expected to contain {expect.contains!r}", None)
    if expect.not_contains is not None:
        return (
            expect.not_contains not in stdout,
            f"expected not to contain {expect.not_contains!r}",
            None,
        )
    return (
        re.search(expect.matches or "", stdout) is not None,
        f"expected to match /{expect.matches}/",
        None,
    )


def _evaluate_compare(
    output: object, spec: dict[str, object]
) -> tuple[bool, str, dict[str, object] | None]:
    # napalm's compare mutates BOTH arguments (spec `_mode` pops, matched list
    # elements pop) — deep-copy so the stored expectation and parsed output
    # survive intact.
    try:
        verdict = napalm_validate.compare(copy.deepcopy(spec), copy.deepcopy(output))
    except (ValidationException, ValueError, TypeError, re.error) as exc:
        return (False, f"compare failed to evaluate: {exc}", None)
    if isinstance(verdict, dict):
        report = verdict
        complies = bool(report.get("complies"))
        return (complies, "compare spec " + ("held" if complies else "did not hold"), report)
    return (bool(verdict), f"compare spec {'held' if verdict else 'did not hold'}", None)


# --------------------------------------------------------------------------- #
# The runner
# --------------------------------------------------------------------------- #


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _node_device(node: str, facts: NodeFacts) -> str | None:
    device = facts.get(node, {}).get("device")
    return device if isinstance(device, str) else None


def _resolve_case(test: ValidationTest, node: str, facts: NodeFacts) -> TestCase | None | str:
    """The case this node runs: a TestCase, None for a clean skip (device-keyed
    test, node's device has no case), or an error string."""
    if isinstance(test.run, TestCase):
        return test.run
    device = _node_device(node, facts)
    if device is None:
        return f"node {node!r} is not in the lab's fact namespace"
    return test.run.get(device)


async def _run_check(
    executor: NodeExecutor,
    facts: NodeFacts,
    test_name: str,
    test: ValidationTest,
    node: str,
) -> TestResult:
    """Run one test on one node, polling until it passes or its `wait` window
    elapses. An exec that never succeeds within the window (e.g. the node is
    down) is an `error` — the assertion couldn't be evaluated; a command that
    runs but whose output doesn't match is a `fail`. Render and parse failures
    are `error`s too: they mean the check itself is broken, not the network."""
    started = time.monotonic()

    def result(
        status: Literal["pass", "fail", "skip", "error"],
        command: str,
        output: str,
        detail: str,
        diff: dict[str, object] | None = None,
    ) -> TestResult:
        return TestResult(
            test=test_name,
            node=node,
            status=status,
            command=command,
            output=output[:_MAX_OUTPUT_CHARS],
            detail=detail,
            diff=diff,
            elapsed_ms=_elapsed_ms(started),
        )

    case = _resolve_case(test, node, facts)
    if isinstance(case, str):
        return result("error", "", "", case)
    if case is None:
        device = _node_device(node, facts)
        return result("skip", "", "", f"no case for device {device!r}")

    command = render_template(case.command, node, facts)
    if isinstance(command, Err):
        return result("error", case.command, "", command.error)
    expect = render_expectation(case.expect, node, facts)
    if isinstance(expect, Err):
        return result("error", command.value, "", expect.error)
    device = _node_device(node, facts) or ""

    deadline = started + test.wait
    while True:
        run = await executor(node, command.value, case.interactive)
        if isinstance(run, Err):
            if time.monotonic() < deadline:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue
            return result("error", command.value, "", f"exec failed: {run.error}")
        parsed = parse_output(case, device, run.value)
        if isinstance(parsed, Err):
            # A parse failure can be transient mid-convergence (e.g. empty
            # output while a daemon starts); retry inside the window, then
            # report the check as broken — never silently fall back to raw.
            if time.monotonic() < deadline:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue
            return result("error", command.value, run.value, parsed.error)
        passed, detail, diff = evaluate_expectation(parsed.value, expect.value)
        if passed or time.monotonic() >= deadline:
            return result("pass" if passed else "fail", command.value, run.value, detail, diff)
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def run_suite(
    executor: NodeExecutor, facts: NodeFacts, suite_name: str, suite: TestSuite
) -> SuiteReport:
    """Run every (test, node) in a suite and tally the outcomes. The executor
    resolves each node's transport (netlab exec); `facts` supplies the render
    namespace and each node's device for case resolution."""
    results = [
        await _run_check(executor, facts, test_name, test, node)
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
    executor: NodeExecutor, facts: NodeFacts, suites: dict[str, TestSuite]
) -> list[SuiteReport]:
    """Run the `config-time` suites (in declaration order) — the automatic gate
    at the end of a configure. Runtime suites are left for on-demand runs."""
    return [
        await run_suite(executor, facts, name, suite)
        for name, suite in suites.items()
        if suite.stage == "config-time"
    ]
