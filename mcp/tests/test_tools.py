"""The tools over the real ASGI app and the real client, with the backend
faked at its HTTP boundary."""

import json
from typing import cast

import httpx2
import pytest
from _support import (
    GOOD_KEY,
    JOB_ID,
    FakeBackend,
    action_wire,
    app_for,
    connect,
    job_wire,
    lab_wire,
)
from mcp_types import CallToolResult, TextContent

from twinlab_mcp import tools

READ_TOOLS = {
    "whoami",
    "list_labs",
    "get_lab",
    "list_jobs",
    "get_job",
    "wait_job",
    "get_links",
    "get_interfaces",
    "get_facts",
    "get_usage",
    "node_logs",
    "show_netem",
    "get_test_suites",
    "device_catalog",
    "host_resources",
    "list_network_templates",
    "get_network_template",
}
# name -> (destructive, idempotent)
ACT_TOOLS = {
    "create_lab": (False, False),
    "update_definition": (False, True),
    "deploy_lab": (True, False),
    "configure_lab": (False, False),
    "put_test_suites": (False, True),
    "run_test_suite": (False, False),
    "dry_run_test_case": (False, False),
    "lab_power": (True, False),
    "node_power": (True, False),
    "set_netem": (False, True),
    "save_config": (False, True),
    "destroy_lab": (True, False),
}


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def _error(result: CallToolResult) -> dict[str, object]:
    """The envelope, after the SDK's own `Error executing tool <name>: `."""
    assert result.is_error
    _, _, envelope = _text(result).partition(": ")
    return cast("dict[str, object]", json.loads(envelope))


def _structured(result: CallToolResult) -> dict[str, object]:
    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    return result.structured_content


async def test_the_tool_set_and_its_hints() -> None:
    async with connect(app_for(FakeBackend())) as client:
        listed = (await client.list_tools()).tools
    by_name = {tool.name: tool for tool in listed}
    assert set(by_name) == READ_TOOLS | set(ACT_TOOLS)
    for name in READ_TOOLS:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True, name
    for name, (destructive, idempotent) in ACT_TOOLS.items():
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False, name
        assert annotations.destructive_hint is destructive, name
        assert annotations.idempotent_hint is idempotent, name
    for tool in listed:
        assert tool.description, f"{tool.name} has no description"


async def test_a_tool_acts_with_the_callers_key() -> None:
    backend = FakeBackend()
    backend.json("GET", "/labs", [])
    async with connect(app_for(backend)) as client:
        result = await client.call_tool("list_labs", {})
    assert _structured(result) == {"labs": []}
    assert backend.sent("GET", "/labs").headers["authorization"] == f"Bearer {GOOD_KEY}"


@pytest.mark.parametrize(("drifted", "included"), [(False, False), (None, False), (True, True)])
async def test_get_lab_carries_the_deployed_definition_only_when_drifted(
    drifted: bool | None, included: bool
) -> None:
    backend = FakeBackend()
    backend.json("GET", "/labs/lab1", lab_wire(definition_drifted=drifted))
    async with connect(app_for(backend)) as client:
        lab = _structured(await client.call_tool("get_lab", {"lab": "lab1"}))
    assert ("deployed_definition" in lab) is included
    assert lab["definition"] == "provider: clab\n"


async def test_an_api_error_is_a_tool_result_carrying_the_envelope() -> None:
    backend = FakeBackend()
    envelope = {
        "code": "netlab_invalid",
        "message": "netlab rejected the definition",
        "extras": {"stderr": "ERROR: nodes.r1: device is not set"},
    }
    backend.json("PUT", "/labs/lab1", envelope, status=422)
    async with connect(app_for(backend)) as client:
        result = await client.call_tool(
            "update_definition", {"lab": "lab1", "definition": "nodes: [r1]\n"}
        )
    assert _error(result) == {"status": 422, **envelope}


async def test_a_refused_permission_is_a_tool_error() -> None:
    backend = FakeBackend()
    backend.json(
        "POST",
        "/labs/lab1/deploy",
        {"code": "permission_denied", "message": "lab:edit required", "extras": {}},
        status=403,
    )
    async with connect(app_for(backend)) as client:
        result = await client.call_tool("deploy_lab", {"lab": "lab1", "configure": True})
    assert _error(result)["code"] == "permission_denied"


async def test_an_unreachable_backend_is_a_tool_error() -> None:
    backend = FakeBackend()

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    backend.routes["GET", "/host"] = refuse
    async with connect(app_for(backend)) as client:
        result = await client.call_tool("host_resources", {})
    assert result.is_error
    assert "could not be reached" in _text(result)


async def test_wait_job_returns_a_finished_job() -> None:
    backend = FakeBackend()
    finished = job_wire(status="succeeded", finished_at="2026-09-23T10:05:00+00:00")
    backend.json("GET", f"/labs/lab1/jobs/{JOB_ID}", finished)
    async with connect(app_for(backend)) as client:
        job = _structured(await client.call_tool("wait_job", {"lab": "lab1", "job_id": JOB_ID}))
    assert job["status"] == "succeeded"


async def test_wait_job_returns_a_still_running_job_at_its_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "WAIT_JOB_POLL_SECONDS", 0.05)
    backend = FakeBackend()
    backend.json("GET", f"/labs/lab1/jobs/{JOB_ID}", job_wire())
    async with connect(app_for(backend)) as client:
        result = await client.call_tool(
            "wait_job", {"lab": "lab1", "job_id": JOB_ID, "timeout_seconds": 1}
        )
    assert _structured(result)["status"] == "running"


async def test_wait_job_is_bounded() -> None:
    async with connect(app_for(FakeBackend())) as client:
        result = await client.call_tool(
            "wait_job",
            {"lab": "lab1", "job_id": JOB_ID, "timeout_seconds": tools.WAIT_JOB_MAX_SECONDS + 1},
        )
    assert result.is_error


async def test_set_netem_states_the_complete_impairment() -> None:
    backend = FakeBackend()
    backend.json("POST", "/labs/lab1/nodes/r1/netem", action_wire())
    async with connect(app_for(backend)) as client:
        result = await client.call_tool(
            "set_netem",
            {
                "lab": "lab1",
                "node": "r1",
                "interface": "eth1",
                "delay": {"value": 20, "unit": "ms"},
                "loss": 1.5,
            },
        )
    assert not result.is_error, _text(result)
    assert backend.sent_json("POST", "/labs/lab1/nodes/r1/netem") == {
        "interface": "eth1",
        "delay": {"value": 20.0, "unit": "ms"},
        "jitter": None,
        "loss": 1.5,
        "rate": None,
        "corruption": None,
    }


async def test_put_test_suites_passes_device_keyed_cases_through() -> None:
    backend = FakeBackend()
    backend.json(
        "PUT",
        "/labs/lab1/test-suites",
        {"test_suites": {}, "last_validation": {}, "config_time_status": "not_run"},
    )
    suites = {
        "smoke": {
            "stage": "runtime",
            "tests": {
                "ospf": {
                    "all_nodes": True,
                    "run": {
                        "vyos": {"command": "show ip ospf neighbor", "expect": {"contains": "Full"}}
                    },
                }
            },
        }
    }
    async with connect(app_for(backend)) as client:
        result = await client.call_tool("put_test_suites", {"lab": "lab1", "suites": suites})
    assert not result.is_error, _text(result)
    body = backend.sent_json("PUT", "/labs/lab1/test-suites")
    smoke = cast("dict[str, dict[str, dict[str, object]]]", body["test_suites"])["smoke"]
    ospf = cast("dict[str, object]", smoke["tests"]["ospf"])
    assert ospf["all_nodes"] is True
    run = cast("dict[str, dict[str, object]]", ospf["run"])
    assert run["vyos"]["command"] == "show ip ospf neighbor"


async def test_deploy_lab_requires_configure_to_be_stated() -> None:
    async with connect(app_for(FakeBackend())) as client:
        result = await client.call_tool("deploy_lab", {"lab": "lab1"})
    assert result.is_error


async def test_destroy_lab_passes_remove() -> None:
    backend = FakeBackend()
    backend.json("DELETE", "/labs/lab1", job_wire(kind="destroy"))
    async with connect(app_for(backend)) as client:
        result = await client.call_tool("destroy_lab", {"lab": "lab1", "remove": True})
    assert _structured(result)["kind"] == "destroy"
    assert backend.sent("DELETE", "/labs/lab1").url.params["remove"] == "true"
