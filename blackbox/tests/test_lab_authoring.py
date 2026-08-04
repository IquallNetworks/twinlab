"""Authoring on a lab record: test suites and custom-config templates.

All cheap (no deploys) — suites/templates only take effect on the next
configure, which never happens here.
"""

import pytest
from twinlab_client import (
    LayoutGroupStyle,
    LayoutPosition,
    TestCase,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    ValidationTest,
)

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

_SUITES = {
    "smoke": TestSuite(
        tests={
            "lo_up": ValidationTest(
                nodes=["n1", "n2"],
                run=TestCase(
                    command="ip -o link show lo",
                    expect=TestExpectation(contains="UP"),
                ),
                wait=10,
                description="loopback is up",
            ),
            "keyed": ValidationTest(
                nodes=["n1"],
                run={
                    "linux": TestCase(
                        command="echo {{ node.name }}",
                        expect=TestExpectation(contains="n1"),
                    ),
                    "iol": TestCase(
                        command="show version",
                        expect=TestExpectation(compare={"list": [{"version": ".+"}]}),
                        parse="textfsm",
                        interactive=True,
                    ),
                },
            ),
        },
        stage="config-time",
        description="black-box smoke suite",
    )
}


async def test_test_suites_roundtrip(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)

    initial = await admin.get_test_suites(lab.name)
    assert initial.test_suites == {}
    assert initial.last_validation == {}
    assert initial.config_time_status == "not_run"

    stored = await admin.put_test_suites(lab.name, _SUITES)
    assert stored.test_suites == _SUITES
    assert stored.last_validation == {}  # authoring never runs anything
    assert stored.config_time_status == "not_run"

    fetched = await admin.get_test_suites(lab.name)
    assert fetched.test_suites == _SUITES


async def test_test_suites_full_replace(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    _ = await admin.put_test_suites(lab.name, _SUITES)
    replaced = await admin.put_test_suites(lab.name, {})
    assert replaced.test_suites == {}


async def test_expectation_requires_exactly_one_matcher(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    two_matchers = {
        "bad": TestSuite(
            tests={
                "t": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(command="true", expect=TestExpectation(contains="a", matches="b")),
                )
            }
        )
    }
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_test_suites(lab.name, two_matchers)
    assert excinfo.value.status_code == 422


async def test_compare_without_parse_is_422(admin: TwinlabClient, make_lab: LabFactory) -> None:
    # compare asserts over PARSED data — a case declaring one without the
    # other is a schema error (delta 17, server-checked both ways).
    lab = await make_lab(None)
    unpaired = {
        "bad": TestSuite(
            tests={
                "t": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(command="true", expect=TestExpectation(compare={"a": "b"})),
                )
            }
        )
    }
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_test_suites(lab.name, unpaired)
    assert excinfo.value.status_code == 422


async def test_template_invalid_is_422_with_problems(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    # Bad SYNTAX is rejected even on a bare record (no facts needed) …
    bad_syntax = {
        "bad": TestSuite(
            tests={
                "t": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(command="{{ oops", expect=TestExpectation(contains="x")),
                )
            }
        )
    }
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_test_suites(lab.name, bad_syntax)
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "template_invalid"
    assert excinfo.value.extras.get("problems")

    # … and once the lab has a definition (facts exist), an undefined
    # reference fails the dry render too.
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    bad_ref = {
        "bad": TestSuite(
            tests={
                "t": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(
                        command="ping {{ nodes.ghost.loopback.ipv4 }}",
                        expect=TestExpectation(contains="x"),
                    ),
                )
            }
        )
    }
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_test_suites(lab.name, bad_ref)
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "template_invalid"


async def test_facts_before_definition_is_409(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.facts(lab.name)
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "no_definition"


async def test_facts_namespace_from_authored_record(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    facts = await admin.facts(lab.name)
    # The namespace is netlab's raw node data (provisional/unpinned): only its
    # outer shape and load-bearing keys are asserted.
    assert set(facts.nodes) == {"n1", "n2"}
    assert facts.nodes["n1"]["device"] == "linux"
    assert isinstance(facts.nodes["n1"].get("interfaces"), list)


async def test_run_unknown_suite_is_404(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.run_test_suite(lab.name, "bb-no-such-suite")
    assert excinfo.value.status_code == 404


async def test_builtin_templates_listed(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    response = await admin.get_custom_config(lab.name)
    assert response.custom_config == {}

    # Pinned in the contract's shipped-catalogs appendix: renaming a builtin
    # is a contract + suite change.
    builtin = {template.name: template for template in response.builtin}
    assert {"mpls_te", "ip_sla"} <= set(builtin)
    for template in builtin.values():
        assert template.files, template.name
        assert all(path.endswith(".j2") for path in template.files)


async def test_custom_config_roundtrip_and_full_replace(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    fileset = {"bb_probe.j2": "! {{ inventory_hostname }}\n"}

    stored = await admin.put_custom_config(lab.name, fileset)
    assert stored.custom_config == fileset

    fetched = await admin.get_custom_config(lab.name)
    assert fetched.custom_config == fileset

    cleared = await admin.put_custom_config(lab.name, {})
    assert cleared.custom_config == {}


async def test_custom_config_cannot_shadow_builtin(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_custom_config(lab.name, {"mpls_te.j2": "! shadow\n"})
    assert excinfo.value.status_code == 409


async def test_custom_config_rejects_traversal_paths(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_custom_config(lab.name, {"../evil.j2": "!\n"})
    assert excinfo.value.status_code == 422


async def test_links_before_definition_is_409(admin: TwinlabClient, make_lab: LabFactory) -> None:
    # A bare created record has nothing to derive links from — an empty table
    # would be indistinguishable from a definition with no links (delta 14).
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.links(lab.name)
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "no_definition"


async def test_layout_roundtrip_replace_and_clear(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    # Delta 19: one shared arrangement per lab, opaque canvas-id keys. Unlike
    # links/facts the read is NOT definition-gated — an empty layout on a bare
    # record is honest, not a lie.
    lab = await make_lab(None)
    initial = await admin.get_layout(lab.name)
    assert initial.positions == {}
    assert initial.groups == {}

    stored = await admin.put_layout(
        lab.name,
        {"n1": LayoutPosition(x=10.5, y=-3.0), "link:1": LayoutPosition(x=0.0, y=42.0)},
        groups={"pe": LayoutGroupStyle(color="#f59e0b")},
    )
    assert stored.positions["link:1"].y == 42.0
    assert stored.groups["pe"].color == "#f59e0b"
    fetched = await admin.get_layout(lab.name)
    assert fetched == stored

    # Full REPLACE of the WHOLE resource: a PUT drops every key it doesn't
    # name — omitting `groups` clears the styles too; {} clears everything.
    replaced = await admin.put_layout(lab.name, {"n2": LayoutPosition(x=1.0, y=1.0)})
    assert set(replaced.positions) == {"n2"}
    assert replaced.groups == {}
    cleared = await admin.put_layout(lab.name, {})
    assert cleared.positions == {}

    # Delta 20: color is pinned to #rrggbb — anything else is a 422, so a
    # style can't smuggle arbitrary CSS.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.put_layout(lab.name, {}, groups={"g": LayoutGroupStyle(color="red")})
    assert excinfo.value.status_code == 422


async def test_layout_write_needs_lab_edit(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    # Arranging the shared layout is authoring: lab:read may look, only
    # lab:edit may write (the Build tab's permission).
    lab = await make_lab(None)
    summary, viewer = await make_user_client(None)
    _ = await admin.create_grant(lab.name, "user", summary.id, "lab_viewer")

    layout = await viewer.get_layout(lab.name)
    assert layout.positions == {}
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await viewer.put_layout(lab.name, {"n1": LayoutPosition(x=0.0, y=0.0)})
    assert excinfo.value.status_code == 403


async def test_links_table_from_authored_record(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)

    table = await admin.links(lab.name)
    # Undeployed: the full table is served with states honestly unknown.
    assert table.live is False
    (link,) = table.links  # the definition's single n1-n2 link, one LOGICAL entry
    # Endpoint facts only — `type` is netlab's vocabulary and not asserted.
    assert {endpoint.node for endpoint in link.endpoints} == {"n1", "n2"}
    assert all(endpoint.interface for endpoint in link.endpoints)
    assert link.oper_state == "unknown"
    assert all(e.state is None and e.impairment is None for e in link.endpoints)
