"""TwinlabClient over httpx.MockTransport: request shapes and response parsing."""

import json
from collections.abc import Callable
from typing import cast
from uuid import UUID

import httpx
import pytest

from twinlab_client import (
    DeployResponse,
    Duration,
    LabDetail,
    LabNodeState,
    Principal,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    ValidationTest,
)
from twinlab_client.client import TwinlabClient

ClientFactory = Callable[[Callable[[httpx.Request], httpx.Response]], TwinlabClient]

_OWNER_ID = "0198c0de-0000-7000-8000-000000000001"

_LAB_DETAIL = {
    "name": "lab1",
    "status": "deployed",
    "definition": "provider: clab\n",
    "owner": {"id": _OWNER_ID, "name": "admin"},
    "created_at": "2026-07-23T10:00:00+00:00",
    "updated_at": "2026-07-23T11:00:00+00:00",
    "nodes": [
        {
            "name": "r1",
            "container": "clab-lab1-r1",
            "image": "vyos:1.4",
            "state": "running",
            "mgmt_ip": "192.168.121.101",
        }
    ],
    "config_time_status": "passed",
    "permissions": ["lab:read", "lab:edit"],
}


def _json_body(request: httpx.Request) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(request.content.decode()))


async def test_login_sets_cookie_and_parses(make_client: ClientFactory) -> None:
    seen_cookie_header: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            assert _json_body(request) == {"username": "admin", "password": "pw12345678"}
            return httpx.Response(
                200,
                json={"username": "admin", "roles": ["admin"], "permissions": ["user:manage"]},
                headers={"Set-Cookie": "twinlab_session=tok123; Path=/; HttpOnly"},
            )
        seen_cookie_header.append(request.headers.get("Cookie"))
        return httpx.Response(
            200, json={"username": "admin", "roles": ["admin"], "permissions": ["user:manage"]}
        )

    async with make_client(handler) as client:
        info = await client.login("admin", "pw12345678")
        assert info.username == "admin"
        assert info.roles == {"admin"}
        _ = await client.me()
    assert seen_cookie_header == ["twinlab_session=tok123"]


async def test_api_key_sends_bearer_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tl_secret"
        return httpx.Response(200, json={"username": "ci", "roles": [], "permissions": []})

    async with TwinlabClient(
        "http://testserver", api_key="tl_secret", transport=httpx.MockTransport(handler)
    ) as client:
        _ = await client.me()


async def test_non_2xx_raises_api_error(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "lab_not_found", "message": "no such lab"})

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.get_lab("ghost")
    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "lab_not_found"


async def test_get_lab_parses_detail(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1"
        return httpx.Response(200, json=_LAB_DETAIL)

    async with make_client(handler) as client:
        detail = await client.get_lab("lab1")
    assert isinstance(detail, LabDetail)
    assert detail.owner == Principal(id=UUID(_OWNER_ID), name="admin")
    assert detail.nodes == [
        LabNodeState(
            name="r1",
            container="clab-lab1-r1",
            image="vyos:1.4",
            state="running",
            mgmt_ip="192.168.121.101",
        )
    ]
    assert detail.permissions == {"lab:read", "lab:edit"}
    assert detail.config_time_status == "passed"


async def test_create_lab_posts_name_only(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs"
        assert _json_body(request) == {"name": "lab1"}
        created = dict(_LAB_DETAIL) | {"status": "created", "definition": None, "nodes": []}
        return httpx.Response(201, json=created)

    async with make_client(handler) as client:
        detail = await client.create_lab("lab1")
    assert detail.status == "created"
    assert detail.definition is None


async def test_deploy_lab_body_and_parse(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/deploy"
        assert _json_body(request) == {"configure": True, "skip_config_time_checks": False}
        return httpx.Response(
            200,
            json={
                "status": "configured",
                "lab_name": "lab1",
                "nodes": ["r1", "r2"],
                "configuration": [
                    {"node": "r1", "status": "configured", "changed": 3, "failed": 0},
                    {"node": "r2", "status": "configured", "changed": 3, "failed": 0},
                ],
                "validation": None,
            },
        )

    async with make_client(handler) as client:
        result = await client.deploy_lab("lab1", configure=True)
    assert isinstance(result, DeployResponse)
    assert result.status == "configured"
    assert result.configuration is not None and len(result.configuration) == 2
    assert result.validation is None


async def test_destroy_lab_remove_param(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.params["remove"] == "true"
        return httpx.Response(200, json={"status": "deleted", "detail": "torn down"})

    async with make_client(handler) as client:
        result = await client.destroy_lab("lab1", remove=True)
    assert result.status == "deleted"


async def test_put_test_suites_omits_none_expectation_fields(
    make_client: ClientFactory,
) -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "test_suites": body["test_suites"],
                "last_validation": {},
                "config_time_status": "not_run",
            },
        )

    suites = {
        "smoke": TestSuite(
            tests={
                "ospf": ValidationTest(
                    nodes=["r1"],
                    command="show ip ospf neighbor",
                    expect=TestExpectation(contains="Full"),
                    wait=60,
                )
            },
            stage="config-time",
        )
    }
    async with make_client(handler) as client:
        response = await client.put_test_suites("lab1", suites)

    expect_wire = sent[0]
    assert expect_wire == {
        "test_suites": {
            "smoke": {
                "tests": {
                    "ospf": {
                        "nodes": ["r1"],
                        "command": "show ip ospf neighbor",
                        "expect": {"contains": "Full"},
                        "wait": 60,
                        "description": "",
                    }
                },
                "stage": "config-time",
                "description": "",
            }
        }
    }
    assert response.test_suites == suites
    assert response.config_time_status == "not_run"


async def test_set_netem_replace_semantics_body(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/nodes/r1/netem"
        assert _json_body(request) == {
            "interface": "eth1",
            "delay": {"value": 50.0, "unit": "ms"},
            "jitter": None,
            "loss": 1.5,
            "rate": None,
            "corruption": None,
        }
        return httpx.Response(200, json={"message": "netem applied"})

    async with make_client(handler) as client:
        result = await client.set_netem("lab1", "r1", "eth1", delay=Duration(50.0, "ms"), loss=1.5)
    assert result.message == "netem applied"


async def test_show_netem_parses_durations(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "interface": "eth1",
                    "delay": {"value": 50, "unit": "ms"},
                    "jitter": None,
                    "loss": 0,
                    "rate": 0,
                    "corruption": 0,
                }
            ],
        )

    async with make_client(handler) as client:
        impairments = await client.show_netem("lab1", "r1")
    assert impairments[0].delay == Duration(50.0, "ms")
    assert impairments[0].jitter is None


async def test_interfaces_node_filter_param(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["node"] == "r1"
        return httpx.Response(200, json=[{"node": "r1", "interfaces": []}])

    async with make_client(handler) as client:
        inventory = await client.interfaces("lab1", node="r1")
    assert inventory[0].node == "r1"


async def test_ready_parses_503_as_degraded(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"status": "degraded", "checks": {"database": "connection refused"}}
        )

    async with make_client(handler) as client:
        readiness = await client.ready()
    assert readiness.status == "degraded"
    assert readiness.checks == {"database": "connection refused"}


async def test_events_yields_events_and_skips_keepalives(make_client: ClientFactory) -> None:
    body = (
        'data: {"lab": "lab1", "node": "r1", "action": "start", "timestamp": "t1"}\n\n'
        ": keepalive\n\n"
        'data: {"lab": "lab1", "node": null, "action": "destroy", "timestamp": "t2"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/events"
        return httpx.Response(200, text=body)

    async with make_client(handler) as client:
        events = [event async for event in client.events()]
    assert [event.action for event in events] == ["start", "destroy"]
    assert events[0].node == "r1"
    assert events[1].node is None
