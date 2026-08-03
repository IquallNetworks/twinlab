import json

import pydantic
import pytest

from twinlab_backend.models import TestCase, TestExpectation, TestSuite, ValidationTest
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.validation import (
    NodeExecutor,
    NodeFacts,
    check_suite_templates,
    evaluate_expectation,
    parse_output,
    render_expectation,
    render_template,
    run_suite,
)

# A minimal fact namespace: two nodes, netlab-shaped keys.
_FACTS: NodeFacts = {
    "r1": {
        "device": "vyos",
        "loopback": {"ipv4": "10.0.0.1/32"},
        "interfaces": [{"ifname": "eth1", "ipv4": "10.1.0.1/30"}],
    },
    "r2": {"device": "iol", "loopback": {"ipv4": "10.0.0.2/32"}},
    "h1": {"device": "linux"},
}


def _case(expect: TestExpectation, **kwargs: object) -> TestCase:
    return TestCase.model_validate({"command": "show", "expect": expect, **kwargs})


# --- Schema (models) ---


def test_expectation_requires_exactly_one_matcher() -> None:
    with pytest.raises(pydantic.ValidationError, match="exactly one of"):
        _ = TestExpectation()
    with pytest.raises(pydantic.ValidationError, match="exactly one of"):
        _ = TestExpectation(contains="a", matches="b")


def test_bad_regex_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError, match="not a valid regex"):
        _ = TestExpectation(matches="(")


def test_compare_and_parse_go_together() -> None:
    with pytest.raises(pydantic.ValidationError, match="compare and parse go together"):
        _ = TestCase(command="show", expect=TestExpectation(compare={"a": "b"}))
    with pytest.raises(pydantic.ValidationError, match="compare and parse go together"):
        _ = TestCase(command="show", expect=TestExpectation(contains="a"), parse="json")
    ok = TestCase(command="show", expect=TestExpectation(compare={"a": "b"}), parse="json")
    assert ok.parse == "json"


def test_device_keyed_run_must_not_be_empty() -> None:
    with pytest.raises(pydantic.ValidationError, match="at least one case"):
        _ = ValidationTest(nodes=["r1"], run={})


# --- Render ---


def test_render_template_against_facts() -> None:
    rendered = render_template(
        "ping {{ nodes.r2.loopback.ipv4 | address }} from {{ node.device }}", "r1", _FACTS
    )
    assert rendered == Ok("ping 10.0.0.2 from vyos")


def test_render_undefined_variable_is_an_error() -> None:
    rendered = render_template("{{ nodes.r9.loopback }}", "r1", _FACTS)
    assert isinstance(rendered, Err)


def test_render_expectation_renders_compare_keys_and_values() -> None:
    expect = TestExpectation(
        compare={"peers": {"{{ nodes.r2.loopback.ipv4 | address }}": {"state": "Established"}}}
    )
    rendered = render_expectation(expect, "r1", _FACTS)
    assert isinstance(rendered, Ok)
    assert rendered.value.compare == {"peers": {"10.0.0.2": {"state": "Established"}}}


def test_check_suite_templates_reports_syntax_and_render_problems() -> None:
    suites = {
        "s": TestSuite(
            tests={
                "bad_syntax": ValidationTest(
                    nodes=["r1"],
                    run=TestCase(command="{{ oops", expect=TestExpectation(contains="x")),
                ),
                "bad_ref": ValidationTest(
                    nodes=["r1"],
                    run=TestCase(
                        command="{{ nodes.r9.loopback.ipv4 }}",
                        expect=TestExpectation(contains="x"),
                    ),
                ),
            }
        )
    }
    problems = check_suite_templates(suites, _FACTS)
    assert {p["test"] for p in problems} == {"bad_syntax", "bad_ref"}
    # Without facts, only the syntax problem is checkable.
    syntax_only = check_suite_templates(suites, None)
    assert {p["test"] for p in syntax_only} == {"bad_syntax"}


# --- Parse ---


def test_parse_json() -> None:
    case = _case(TestExpectation(compare={"a": "1"}), parse="json")
    assert parse_output(case, "vyos", '{"a": 1}') == Ok({"a": 1})
    assert isinstance(parse_output(case, "vyos", "not json"), Err)


def test_parse_textfsm_twinlab_ldp_template() -> None:
    # The Twinlab-packaged overlay template (ntc has none for this command),
    # fixture captured live from cisco IOL 17.16 (CRLF endings and all).
    case = TestCase(
        command="show mpls ldp neighbor",
        expect=TestExpectation(compare={"list": [{"state": "Oper"}]}),
        parse="textfsm",
    )
    stdout = (
        "\r\n"
        "    Peer LDP Ident: 10.0.0.5:0; Local LDP Ident 10.0.0.1:0\r\n"
        "\tTCP connection: 10.0.0.5.46757 - 10.0.0.1.646\r\n"
        "\tState: Oper; Msgs sent/rcvd: 22/22; Downstream\r\n"
        "\tUp time: 00:01:26\r\n"
        "\tLDP discovery sources:\r\n"
        "\t  Ethernet0/1, Src IP addr: 10.1.0.1\r\n"
        "        Addresses bound to peer LDP Ident:\r\n"
        "          10.1.0.1        10.0.0.5        \r\n"
    )
    parsed = parse_output(case, "iol", stdout)
    assert parsed == Ok(
        [
            {
                "peer_ldp_ident": "10.0.0.5:0",
                "local_ldp_ident": "10.0.0.1:0",
                "state": "Oper",
                "msgs_sent": "22",
                "msgs_rcvd": "22",
                "uptime": "00:01:26",
            }
        ]
    )


def test_parse_textfsm_missing_template_is_an_error() -> None:
    case = TestCase(
        command="show nonexistent thing",
        expect=TestExpectation(compare={"a": "b"}),
        parse="textfsm",
    )
    result = parse_output(case, "iol", "whatever")
    assert isinstance(result, Err)
    assert "no TextFSM template" in result.error


def test_parse_textfsm_unmapped_device_is_an_error() -> None:
    case = _case(TestExpectation(compare={"a": "b"}), parse="textfsm")
    result = parse_output(case, "frr", "whatever")
    assert isinstance(result, Err)
    assert "platform mapping" in result.error


# --- Assert ---


def test_raw_matchers() -> None:
    assert evaluate_expectation("neighbor is Full", TestExpectation(contains="Full"))[0]
    assert not evaluate_expectation("neighbor is Init", TestExpectation(contains="Full"))[0]
    assert evaluate_expectation("no errors here", TestExpectation(not_contains="drop"))[0]
    assert evaluate_expectation("state: FULL/DR", TestExpectation(matches=r"FULL/\w+"))[0]


def test_compare_nested_partial_match_with_diff() -> None:
    data = json.loads('{"peers": {"10.0.0.2": {"state": "Established", "pfxRcd": 3}}}')
    ok, _, diff = evaluate_expectation(
        data, TestExpectation(compare={"peers": {"10.0.0.2": {"state": "Established"}}})
    )
    assert ok and diff is not None and diff["complies"]
    bad, _, bad_diff = evaluate_expectation(
        data, TestExpectation(compare={"peers": {"10.0.0.9": {"state": "Established"}}})
    )
    assert not bad
    assert bad_diff is not None and not bad_diff["complies"]


def test_compare_numeric_operator_and_list() -> None:
    data = json.loads('{"peers": {"a": {"pfxRcd": 5}}}')
    assert evaluate_expectation(data, TestExpectation(compare={"peers": {"a": {"pfxRcd": ">0"}}}))[
        0
    ]
    records = [{"state": "FULL/  -"}, {"state": "FULL/BDR"}]
    assert evaluate_expectation(
        records, TestExpectation(compare={"list": [{"state": "FULL.*"}, {"state": "FULL.*"}]})
    )[0]


def test_compare_broken_spec_is_a_clean_failure() -> None:
    # A numeric operator against non-numeric data raises inside napalm; the
    # boundary adapter turns it into a failed evaluation, not a crash.
    ok, detail, _ = evaluate_expectation(
        {"a": "not-a-number"}, TestExpectation(compare={"a": ">3"})
    )
    assert not ok
    assert "failed to evaluate" in detail


def test_compare_does_not_mutate_the_spec() -> None:
    expect = TestExpectation(compare={"_mode": "strict", "a": "1"})
    _ = evaluate_expectation({"a": 1}, expect)
    assert expect.compare == {"_mode": "strict", "a": "1"}  # napalm pops _mode on a COPY


# --- The runner (over an injected executor) ---


def _executor_ok(stdout: str) -> NodeExecutor:
    async def execute(node: str, command: str, interactive: bool) -> Result[str, str]:
        return Ok(stdout)

    return execute


def _executor_err(message: str) -> NodeExecutor:
    async def execute(node: str, command: str, interactive: bool) -> Result[str, str]:
        return Err(message)

    return execute


def _suite(test: ValidationTest) -> TestSuite:
    return TestSuite(tests={"t": test})


async def test_run_suite_passes_and_renders_command() -> None:
    test = ValidationTest(
        nodes=["r1"],
        run=TestCase(
            command="ping {{ nodes.r2.loopback.ipv4 | address }}",
            expect=TestExpectation(contains="0% packet loss"),
        ),
    )
    report = await run_suite(_executor_ok("... 0% packet loss ..."), _FACTS, "s", _suite(test))
    assert (report.passed, report.failed, report.errored) == (1, 0, 0)
    assert report.results[0].command == "ping 10.0.0.2"  # the RENDERED command


async def test_run_suite_device_keyed_case_and_skip() -> None:
    test = ValidationTest(
        nodes=["r1", "r2", "h1"],
        run={
            "vyos": TestCase(command="show v", expect=TestExpectation(contains="ok")),
            "iol": TestCase(command="show i", expect=TestExpectation(contains="ok")),
        },
    )
    report = await run_suite(_executor_ok("ok"), _FACTS, "s", _suite(test))
    # r1 (vyos) and r2 (iol) run their cases; h1 (linux) has none -> skip.
    assert (report.passed, report.skipped, report.failed, report.errored) == (2, 1, 0, 0)
    by_node = {r.node: r for r in report.results}
    assert by_node["h1"].status == "skip"
    assert "linux" in by_node["h1"].detail


async def test_run_suite_unknown_node_is_an_error() -> None:
    test = ValidationTest(
        nodes=["ghost"],
        run={"vyos": TestCase(command="show", expect=TestExpectation(contains="ok"))},
    )
    report = await run_suite(_executor_ok("ok"), _FACTS, "s", _suite(test))
    assert report.errored == 1
    assert "fact namespace" in report.results[0].detail


async def test_run_suite_parse_failure_is_an_error() -> None:
    test = ValidationTest(
        nodes=["r1"],
        run=TestCase(command="show", expect=TestExpectation(compare={"a": "1"}), parse="json"),
    )
    report = await run_suite(_executor_ok("not json"), _FACTS, "s", _suite(test))
    assert report.errored == 1
    assert "not valid JSON" in report.results[0].detail


async def test_run_suite_exec_failure_is_an_error() -> None:
    test = ValidationTest(
        nodes=["r1"], run=TestCase(command="show", expect=TestExpectation(contains="ok"))
    )
    report = await run_suite(_executor_err("node down"), _FACTS, "s", _suite(test))
    assert report.errored == 1
    assert not report.ok


async def test_run_suite_compare_pipeline_end_to_end() -> None:
    # json parse -> rendered compare key -> napalm verdict, all through run_suite.
    stdout = '{"peers": {"10.0.0.2": {"state": "Established", "pfxRcd": 3}}}'
    test = ValidationTest(
        nodes=["r1"],
        run=TestCase(
            command="show bgp sum json",
            expect=TestExpectation(
                compare={
                    "peers": {
                        "{{ nodes.r2.loopback.ipv4 | address }}": {
                            "state": "Established",
                            "pfxRcd": ">0",
                        }
                    }
                }
            ),
            parse="json",
        ),
    )
    report = await run_suite(_executor_ok(stdout), _FACTS, "s", _suite(test))
    assert report.passed == 1
    assert report.results[0].diff is not None and report.results[0].diff["complies"]
