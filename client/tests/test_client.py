"""TwinlabClient over httpx.MockTransport: request shapes and response parsing."""

import json
from collections.abc import Callable
from typing import cast
from uuid import UUID

import httpx
import pytest

from twinlab_client import (
    DeployResponse,
    DiffSource,
    Duration,
    ImportSource,
    Job,
    JobEvent,
    LabDetail,
    LabEvent,
    LabLayout,
    LabNodeState,
    LayoutGroupStyle,
    LayoutPosition,
    NetemAction,
    PowerAction,
    Principal,
    SshAccess,
    SshKey,
    SshKeyGenerated,
    TestCase,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabProtocolError,
    ValidationTest,
)
from twinlab_client.client import TwinlabClient

ClientFactory = Callable[[Callable[[httpx.Request], httpx.Response]], TwinlabClient]

_OWNER_ID = "0198c0de-0000-7000-8000-000000000001"
_JOB_ID = "0198c0de-0000-7000-8000-00000000000a"


def _job_wire(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": _JOB_ID,
        "lab_name": "lab1",
        "kind": "deploy",
        "status": "running",
        "request": {"configure": True, "skip_config_time_checks": False},
        "result": None,
        "error": None,
        "created_at": "2026-07-29T10:00:00+00:00",
        "finished_at": None,
    }
    return base | overrides


_LAB_DETAIL = {
    "name": "lab1",
    "status": "deployed",
    "definition": "provider: clab\n",
    "deployed_definition": "provider: clab\n",
    "definition_drifted": False,
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
    "template_published": False,
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


_SSH_KEY_ID = "0198c0de-0000-7000-8000-00000000000b"
_SSH_KEY_WIRE = {
    "id": _SSH_KEY_ID,
    "name": "laptop",
    "algorithm": "ssh-ed25519",
    "fingerprint": "SHA256:ZrrsZH82SZKt5kDXdU0J+MGcZiJKt8r2qXKOLcGfqik",
    "comment": "galileo@laptop",
    "created_at": "2026-07-29T10:00:00+00:00",
    "last_used_at": None,
}


async def test_create_ssh_key_body_and_parse(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/ssh-keys"
        assert _json_body(request) == {
            "name": "laptop",
            "public_key": "ssh-ed25519 AAAAC3Nza galileo@laptop",
        }
        return httpx.Response(201, json=_SSH_KEY_WIRE)

    async with make_client(handler) as client:
        key = await client.create_ssh_key("laptop", "ssh-ed25519 AAAAC3Nza galileo@laptop")
    assert isinstance(key, SshKey)
    assert key.id == UUID(_SSH_KEY_ID)
    assert key.algorithm == "ssh-ed25519"
    assert key.fingerprint.startswith("SHA256:")
    assert key.comment == "galileo@laptop"
    assert key.last_used_at is None


async def test_list_and_delete_ssh_keys(make_client: ClientFactory) -> None:
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(204)
        assert request.url.path == "/api/v1/auth/ssh-keys"
        return httpx.Response(200, json=[_SSH_KEY_WIRE])

    async with make_client(handler) as client:
        keys = await client.list_ssh_keys()
        assert [k.name for k in keys] == ["laptop"]
        await client.delete_ssh_key(UUID(_SSH_KEY_ID))
    assert deleted == [f"/api/v1/auth/ssh-keys/{_SSH_KEY_ID}"]


_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"


async def test_generate_ssh_key_body_and_parse(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/ssh-keys/generate"
        assert _json_body(request) == {"name": "laptop"}
        return httpx.Response(201, json={"private_key": _PEM, "info": _SSH_KEY_WIRE})

    async with make_client(handler) as client:
        generated = await client.generate_ssh_key("laptop")
    assert isinstance(generated, SshKeyGenerated)
    assert generated.private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert generated.info.name == "laptop"


async def test_ssh_access_enabled(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/ssh-access"
        return httpx.Response(
            200, json={"enabled": True, "host": "labs.example.com", "port": 2222, "user": "jump"}
        )

    async with make_client(handler) as client:
        access = await client.get_ssh_access()
    assert access == SshAccess(enabled=True, host="labs.example.com", port=2222, user="jump")


async def test_ssh_access_disabled_is_all_none(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"enabled": False, "host": None, "port": None, "user": None}
        )

    async with make_client(handler) as client:
        access = await client.get_ssh_access()
    assert access == SshAccess(enabled=False, host=None, port=None, user=None)


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
    assert detail.deployed_definition == "provider: clab\n"
    assert detail.definition_drifted is False


async def test_get_lab_parses_drift(make_client: ClientFactory) -> None:
    # Delta 19: an edited stored definition reads as drift against the
    # deployed snapshot; both fields are served so a client can diff them.
    drifted = dict(_LAB_DETAIL) | {
        "definition": "provider: clab\nedited: true\n",
        "definition_drifted": True,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=drifted)

    async with make_client(handler) as client:
        detail = await client.get_lab("lab1")
    assert detail.definition_drifted is True
    assert detail.deployed_definition == "provider: clab\n"


async def test_get_layout_parses_positions(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/labs/lab1/layout"
        return httpx.Response(
            200,
            json={
                "positions": {"r1": {"x": 10.5, "y": -3}, "link:3": {"x": 0, "y": 0}},
                "groups": {"pe": {"color": "#f59e0b"}},
            },
        )

    async with make_client(handler) as client:
        layout = await client.get_layout("lab1")
    assert layout == LabLayout(
        positions={
            "r1": LayoutPosition(x=10.5, y=-3.0),
            "link:3": LayoutPosition(x=0.0, y=0.0),
        },
        groups={"pe": LayoutGroupStyle(color="#f59e0b")},
    )


async def test_put_layout_sends_full_replace(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/v1/labs/lab1/layout"
        body = _json_body(request)
        assert body == {
            "positions": {"r1": {"x": 1.0, "y": 2.0}},
            "groups": {"pe": {"color": "#38bdf8"}},
        }
        return httpx.Response(200, json=body)

    async with make_client(handler) as client:
        layout = await client.put_layout(
            "lab1",
            {"r1": LayoutPosition(x=1.0, y=2.0)},
            groups={"pe": LayoutGroupStyle(color="#38bdf8")},
        )
    assert layout.positions["r1"] == LayoutPosition(x=1.0, y=2.0)
    assert layout.groups["pe"].color == "#38bdf8"


async def test_put_layout_empty_clears(make_client: ClientFactory) -> None:
    # Omitting `groups` still replaces the WHOLE resource — styles cleared.
    def handler(request: httpx.Request) -> httpx.Response:
        assert _json_body(request) == {"positions": {}, "groups": {}}
        return httpx.Response(200, json={"positions": {}, "groups": {}})

    async with make_client(handler) as client:
        layout = await client.put_layout("lab1", {})
    assert layout.positions == {}
    assert layout.groups == {}


async def test_get_layout_malformed_position_is_protocol_error(
    make_client: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"positions": {"r1": {"x": "ten", "y": 0}}})

    async with make_client(handler) as client:
        with pytest.raises(TwinlabProtocolError):
            _ = await client.get_layout("lab1")


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


async def test_deploy_lab_submits_and_parses_job(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/deploy"
        assert _json_body(request) == {"configure": True, "skip_config_time_checks": False}
        return httpx.Response(202, json=_job_wire())

    async with make_client(handler) as client:
        job = await client.deploy_lab("lab1", configure=True)
    assert isinstance(job, Job)
    assert job.kind == "deploy"
    assert job.status == "running"
    assert job.result is None and job.error is None
    assert job.finished_at is None
    assert job.request == {"configure": True, "skip_config_time_checks": False}


async def test_destroy_lab_remove_param(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.params["remove"] == "true"
        return httpx.Response(202, json=_job_wire(kind="destroy", request={"remove": True}))

    async with make_client(handler) as client:
        job = await client.destroy_lab("lab1", remove=True)
    assert job.kind == "destroy"
    assert job.status == "running"


async def test_get_job_parses_result_by_kind(make_client: ClientFactory) -> None:
    deploy_result = {
        "status": "configured",
        "lab_name": "lab1",
        "nodes": ["r1", "r2"],
        "configuration": [
            {"node": "r1", "status": "configured", "changed": 3, "failed": 0},
            {"node": "r2", "status": "configured", "changed": 3, "failed": 0},
        ],
        "validation": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/labs/lab1/jobs/{_JOB_ID}"
        return httpx.Response(
            200,
            json=_job_wire(
                status="succeeded",
                result=deploy_result,
                finished_at="2026-07-29T10:05:00+00:00",
            ),
        )

    async with make_client(handler) as client:
        job = await client.get_job("lab1", UUID(_JOB_ID))
    assert job.status == "succeeded"
    assert isinstance(job.result, DeployResponse)
    assert job.result.status == "configured"
    assert job.finished_at is not None


async def test_failed_job_carries_error_envelope(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_job_wire(
                status="failed",
                error={
                    "status_code": 502,
                    "code": "upstream_error",
                    "message": "clab-api unreachable",
                    "extras": {},
                },
                finished_at="2026-07-29T10:05:00+00:00",
            ),
        )

    async with make_client(handler) as client:
        job = await client.get_job("lab1", UUID(_JOB_ID))
    assert job.status == "failed"
    assert job.result is None
    assert job.error is not None
    assert job.error.status_code == 502
    assert job.error.code == "upstream_error"


async def test_list_jobs_sends_limit(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/jobs"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json=[_job_wire()])

    async with make_client(handler) as client:
        jobs = await client.list_jobs("lab1", limit=5)
    assert len(jobs) == 1
    assert jobs[0].kind == "deploy"


async def test_wait_job_polls_to_terminal(make_client: ClientFactory) -> None:
    polls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        polls.append(1)
        if len(polls) < 3:
            return httpx.Response(200, json=_job_wire())
        return httpx.Response(
            200,
            json=_job_wire(
                kind="destroy",
                status="succeeded",
                result={"status": "destroyed", "detail": "torn down"},
                finished_at="2026-07-29T10:05:00+00:00",
            ),
        )

    async with make_client(handler) as client:
        job = await client.wait_job("lab1", UUID(_JOB_ID), poll_interval=0.01)
    assert len(polls) == 3
    assert job.status == "succeeded"


async def test_wait_job_deadline_raises_timeout(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_job_wire())

    async with make_client(handler) as client:
        with pytest.raises(TimeoutError):
            _ = await client.wait_job("lab1", UUID(_JOB_ID), timeout=0.02, poll_interval=0.01)


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
                    nodes=["r1", "r2"],
                    run={
                        "vyos": TestCase(
                            command="vtysh -c 'show ip ospf neighbor json'",
                            expect=TestExpectation(compare={"neighbors": {"_mode": "strict"}}),
                            parse="json",
                        ),
                        "iol": TestCase(
                            command="ping {{ nodes.r1.loopback.ipv4 | address }} repeat 5",
                            expect=TestExpectation(matches="Success rate is 100 percent"),
                            interactive=True,
                        ),
                    },
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
                        "nodes": ["r1", "r2"],
                        "run": {
                            "vyos": {
                                "command": "vtysh -c 'show ip ospf neighbor json'",
                                "expect": {"compare": {"neighbors": {"_mode": "strict"}}},
                                "parse": "json",
                                "interactive": False,
                            },
                            "iol": {
                                "command": "ping {{ nodes.r1.loopback.ipv4 | address }} repeat 5",
                                "expect": {"matches": "Success rate is 100 percent"},
                                "interactive": True,
                            },
                        },
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


async def test_put_test_suites_shared_case_roundtrip(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "test_suites": _json_body(request)["test_suites"],
                "last_validation": {},
                "config_time_status": "not_run",
            },
        )

    suites = {
        "ping": TestSuite(
            tests={
                "lo": ValidationTest(
                    nodes=["h1"],
                    run=TestCase(
                        command="ping -c 3 {{ nodes.h2.loopback.ipv4 | address }}",
                        expect=TestExpectation(matches=" 0% packet loss"),
                    ),
                )
            }
        )
    }
    async with make_client(handler) as client:
        response = await client.put_test_suites("lab1", suites)
    # The shared-case form (one TestCase for every node) round-trips as itself,
    # not as a device-keyed dict.
    assert response.test_suites == suites


async def test_device_catalog_parses(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/catalog"
        return httpx.Response(
            200,
            json={
                "devices": [
                    {
                        "device": "vyos",
                        "label": "VyOS",
                        "role": "router",
                        "modules": ["bgp", "mpls", "ospf", "vrf"],
                        "image": "ghcr.io/sysoleg/vyos-container",
                        "image_present": True,
                        "config_import": True,
                    },
                    {
                        "device": "linux",
                        "label": "Linux host",
                        "role": "host",
                        "modules": [],
                        "image": "python:3.13-alpine",
                        "image_present": None,
                        "config_import": False,
                    },
                ],
                "live": True,
            },
        )

    async with make_client(handler) as client:
        catalog = await client.device_catalog()
    assert catalog.live
    assert [d.device for d in catalog.devices] == ["vyos", "linux"]
    assert catalog.devices[0].role == "router"
    assert catalog.devices[0].image_present is True
    assert catalog.devices[0].config_import is True
    assert catalog.devices[1].image_present is None
    assert catalog.devices[1].config_import is False


async def test_device_catalog_unknown_role_is_protocol_error(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "devices": [
                    {
                        "device": "vyos",
                        "label": "VyOS",
                        "role": "switch",
                        "modules": [],
                        "image": "x",
                        "image_present": None,
                        "config_import": False,
                    }
                ],
                "live": False,
            },
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabProtocolError):
            _ = await client.device_catalog()


async def test_facts_returns_raw_node_namespace(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/facts"
        return httpx.Response(
            200,
            json={"nodes": {"r1": {"device": "vyos", "loopback": {"ipv4": "10.0.0.1/32"}}}},
        )

    async with make_client(handler) as client:
        facts = await client.facts("lab1")
    assert facts.nodes["r1"]["device"] == "vyos"


async def test_facts_no_definition_is_api_error(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"code": "no_definition", "message": "no definition", "extras": {}}
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.facts("lab1")
    assert excinfo.value.code == "no_definition"


async def test_suite_report_with_diff_and_skip_parses(make_client: ClientFactory) -> None:
    report: dict[str, object] = {
        "suite": "conv",
        "stage": "runtime",
        "passed": 1,
        "failed": 0,
        "skipped": 1,
        "errored": 0,
        "ran_at": "2026-08-03T12:00:00+00:00",
        "results": [
            {
                "test": "bgp",
                "node": "r1",
                "status": "pass",
                "command": "show bgp ipv4 vpn summary json",
                "output": "{}",
                "detail": "compare spec held",
                "diff": {"complies": True, "present": {}, "missing": [], "extra": []},
                "elapsed_ms": 12,
            },
            {
                "test": "bgp",
                "node": "h1",
                "status": "skip",
                "command": "",
                "output": "",
                "detail": "no case for device 'linux'",
                "elapsed_ms": 0,
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "test_suites": {},
                "last_validation": {"conv": report},
                "config_time_status": "passed",
            },
        )

    async with make_client(handler) as client:
        response = await client.get_test_suites("lab1")
    results = response.last_validation["conv"].results
    assert results[0].diff is not None and results[0].diff["complies"] is True
    assert results[1].status == "skip" and results[1].diff is None


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
        result = await client.set_netem(
            "lab1", NetemAction(node="r1", interface="eth1", delay=Duration(50.0, "ms"), loss=1.5)
        )
    assert result.message == "netem applied"


async def test_apply_actions_tags_items_and_aligns_results(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/actions"
        # A netem item IS the single route's body + node + kind (delta 24).
        assert _json_body(request) == {
            "actions": [
                {
                    "kind": "netem",
                    "node": "r1",
                    "interface": "eth1",
                    "delay": {"value": 50.0, "unit": "ms"},
                    "jitter": None,
                    "loss": None,
                    "rate": None,
                    "corruption": None,
                },
                {"kind": "power", "node": "r2", "action": "stop"},
            ]
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {"ok": True, "code": None, "message": "impaired eth1"},
                    {"ok": False, "code": "clab_not_found", "message": "no such node"},
                ]
            },
        )

    async with make_client(handler) as client:
        report = await client.apply_actions(
            "lab1",
            [
                NetemAction(node="r1", interface="eth1", delay=Duration(50.0, "ms")),
                PowerAction(node="r2", action="stop"),
            ],
        )
    # A failed item is DATA — the call returns, it does not raise.
    assert [result.ok for result in report.results] == [True, False]
    assert report.results[1].code == "clab_not_found"
    assert report.results[0].code is None


async def test_apply_actions_surfaces_upfront_rejection_as_an_error(
    make_client: ClientFactory,
) -> None:
    # A structurally invalid item never executes: that IS an HTTP error.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422, json={"code": "validation_error", "message": "jitter requires delay", "extras": {}}
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.apply_actions("lab1", [PowerAction(node="r1", action="stop")])
    assert excinfo.value.code == "validation_error"


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


def _link_endpoint_payload(node: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "node": node,
        "interface": "eth1",
        "ifname": "eth1",
        "ifindex": 1,
        "ipv4": "10.0.0.1/30",
        "ipv6": None,
        "state": "up",
        "impairment": None,
    }
    return payload | overrides


def _lab_link_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "index": 1,
        "name": None,
        "type": "p2p",
        "prefix_ipv4": "10.0.0.0/30",
        "prefix_ipv6": None,
        "bandwidth": None,
        "mtu": None,
        "oper_state": "up",
        "endpoints": [_link_endpoint_payload("n1"), _link_endpoint_payload("n2")],
    }
    return payload | overrides


async def test_links_parses_table_and_impairment(make_client: ClientFactory) -> None:
    impaired = _link_endpoint_payload(
        "n1",
        impairment={
            "interface": "eth1",
            "delay": {"value": 50, "unit": "ms"},
            "jitter": None,
            "loss": 0,
            "rate": 0,
            "corruption": 0,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/links"
        return httpx.Response(
            200,
            json={
                "links": [
                    _lab_link_payload(endpoints=[impaired, _link_endpoint_payload("n2")]),
                    _lab_link_payload(
                        index=2,
                        type="lan",
                        oper_state="unknown",
                        endpoints=[
                            _link_endpoint_payload("n1", state=None),
                            _link_endpoint_payload("n2"),
                            _link_endpoint_payload("n3"),
                        ],
                    ),
                ],
                "live": True,
            },
        )

    async with make_client(handler) as client:
        table = await client.links("lab1")
    assert table.live is True
    p2p, lan = table.links
    assert p2p.oper_state == "up"
    assert p2p.endpoints[0].impairment is not None
    assert p2p.endpoints[0].impairment.delay == Duration(50.0, "ms")
    assert p2p.endpoints[1].impairment is None
    assert len(lan.endpoints) == 3  # a LAN is ONE logical link
    assert lan.endpoints[0].state is None


async def test_links_no_definition_raises_api_error(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"code": "no_definition", "message": "lab 'lab1' has no definition", "extras": {}},
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.links("lab1")
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "no_definition"


async def test_links_unknown_oper_state_is_protocol_error(make_client: ClientFactory) -> None:
    # oper_state is pinned (the backend derives it) — an unknown value is a
    # protocol break, not something to tolerate.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"links": [_lab_link_payload(oper_state="flapping")], "live": True}
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabProtocolError):
            _ = await client.links("lab1")


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
        'event: lab\ndata: {"lab": "lab1", "node": "r1", "action": "start", "timestamp": "t1"}\n\n'
        ": keepalive\n\n"
        'event: lab\ndata: {"lab": "lab1", "node": null, "action": "destroy",'
        ' "timestamp": "t2"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/events"
        return httpx.Response(200, text=body)

    async with make_client(handler) as client:
        events = [event async for event in client.events()]
    assert [event for event in events if not isinstance(event, LabEvent)] == []
    lab_events = [event for event in events if isinstance(event, LabEvent)]
    assert [event.action for event in lab_events] == ["start", "destroy"]
    assert lab_events[0].node == "r1"
    assert lab_events[1].node is None


async def test_events_discriminates_job_events_by_name(make_client: ClientFactory) -> None:
    # The two payloads share one stream; the SSE event NAME is what tells them
    # apart (delta 16), so a job event must never be parsed as a lab event.
    body = (
        'event: lab\ndata: {"lab": "lab1", "node": "r1", "action": "start", "timestamp": "t1"}\n\n'
        f'event: job\ndata: {{"lab": "lab1", "job_id": "{_JOB_ID}", "kind": "deploy",'
        ' "status": "succeeded", "timestamp": "2026-07-30T12:00:00Z"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with make_client(handler) as client:
        events = [event async for event in client.events()]
    assert isinstance(events[0], LabEvent)
    job = events[1]
    assert isinstance(job, JobEvent)
    assert job.job_id == UUID(_JOB_ID)
    assert job.kind == "deploy"
    assert job.status == "succeeded"
    assert job.lab == "lab1"


async def test_events_skips_unknown_event_names(make_client: ClientFactory) -> None:
    # Forward compatibility: a shape this client has no parser for is skipped,
    # not fatal — the server may add events without breaking older callers.
    body = (
        'event: horoscope\ndata: {"sign": "leo"}\n\n'
        'event: lab\ndata: {"lab": "lab1", "node": "r1", "action": "start", "timestamp": "t1"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with make_client(handler) as client:
        events = [event async for event in client.events()]
    assert len(events) == 1
    assert isinstance(events[0], LabEvent)


async def test_list_all_jobs_reads_the_fleet_route(make_client: ClientFactory) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[_job_wire()])

    async with make_client(handler) as client:
        jobs = await client.list_all_jobs(limit=50)
    assert seen[0].url.path == "/api/v1/jobs"
    assert seen[0].url.params["limit"] == "50"
    assert [job.lab_name for job in jobs] == ["lab1"]


# --------------------------------------------------------------------------- #
# Template library (delta 21)
# --------------------------------------------------------------------------- #

_NETWORK_TEMPLATE_WIRE = {
    "name": "mpls-l3vpn",
    "tier": "builtin",
    "description": "MPLS L3VPN core on VyOS.",
    "source_lab": None,
}
_NODE_TEMPLATE_WIRE = {
    "name": "pe-router",
    "tier": "user",
    "description": "A PE with the full stack.",
    "device": "vyos",
    "content": "device: vyos\nmodule: [ospf, bgp, mpls, vrf]\n",
}


async def test_list_network_templates_both_tiers(make_client: ClientFactory) -> None:
    published = {
        "name": "lab1",
        "tier": "user",
        "description": "our reference core",
        "source_lab": "lab1",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/templates/network"
        return httpx.Response(200, json=[_NETWORK_TEMPLATE_WIRE, published])

    async with make_client(handler) as client:
        templates = await client.list_network_templates()
    assert [t.tier for t in templates] == ["builtin", "user"]
    assert templates[1].source_lab == "lab1"


async def test_get_network_template_serves_content(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/templates/network/mpls-l3vpn"
        return httpx.Response(200, json=_NETWORK_TEMPLATE_WIRE | {"content": "provider: clab\n"})

    async with make_client(handler) as client:
        template = await client.get_network_template("mpls-l3vpn")
    assert template.content == "provider: clab\n"
    assert template.tier == "builtin"


async def test_node_template_crud_request_shapes(make_client: ClientFactory) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        status = 201 if request.method == "POST" else 200
        return httpx.Response(status, json=_NODE_TEMPLATE_WIRE)

    async with make_client(handler) as client:
        created = await client.create_node_template(
            "pe-router",
            description="A PE with the full stack.",
            content="device: vyos\nmodule: [ospf, bgp, mpls, vrf]\n",
        )
        _ = await client.update_node_template(
            "pe-router", description="updated", content="device: vyos\n"
        )
        await client.delete_node_template("pe-router")

    assert created.device == "vyos"
    assert seen[0].method == "POST" and seen[0].url.path == "/api/v1/templates/node"
    assert _json_body(seen[0]) == {
        "name": "pe-router",
        "description": "A PE with the full stack.",
        "content": "device: vyos\nmodule: [ospf, bgp, mpls, vrf]\n",
    }
    assert seen[1].method == "PUT" and seen[1].url.path == "/api/v1/templates/node/pe-router"
    assert _json_body(seen[1]) == {"description": "updated", "content": "device: vyos\n"}
    assert seen[2].method == "DELETE" and seen[2].url.path == "/api/v1/templates/node/pe-router"


async def test_set_lab_template_publish_and_withdraw(make_client: ClientFactory) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json_body(request)
        seen.append(body)
        assert request.url.path == "/api/v1/labs/lab1/template"
        if body["published"]:
            return httpx.Response(
                200,
                json={
                    "name": "lab1",
                    "tier": "user",
                    "description": body["description"],
                    "source_lab": "lab1",
                },
            )
        # A withdraw answers a JSON null body (httpx's json= treats None as
        # "no body", so spell the wire form out).
        return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})

    async with make_client(handler) as client:
        entry = await client.set_lab_template("lab1", published=True, description="the card")
        withdrawn = await client.set_lab_template("lab1", published=False)

    assert entry is not None and entry.tier == "user" and entry.description == "the card"
    assert withdrawn is None
    assert seen == [
        {"published": True, "description": "the card"},
        {"published": False, "description": None},
    ]


async def test_node_template_bad_tier_is_protocol_error(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_NODE_TEMPLATE_WIRE | {"tier": "communal"}])

    async with make_client(handler) as client:
        with pytest.raises(TwinlabProtocolError):
            _ = await client.list_node_templates()


async def test_lab_detail_serves_template_published(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LAB_DETAIL | {"template_published": True})

    async with make_client(handler) as client:
        detail = await client.get_lab("lab1")
    assert detail.template_published is True


# --------------------------------------------------------------------------- #
# Config import (delta 22)
# --------------------------------------------------------------------------- #

_NETWORK_IMPORT_PAYLOAD = {
    "definition": "provider: clab\nnodes:\n  r1:\n    device: iol\n",
    "custom_config": {
        "imported/r1.j2": "{% raw %}\ninterface Ethernet0/1\n{% endraw %}\n",
        "imported/r1.quarantine.j2": "{% raw %}\naaa new-model\n{% endraw %}\n",
    },
    "interface_map": {"r1": {"GigabitEthernet0/0/1": "Ethernet0/1"}},
    "name_map": {"prod-r1": "prod_r1"},
    "quarantine": {"r1": [{"reason": "auth", "content": "aaa new-model"}]},
    "warnings": [{"node": "r1", "message": "something noted"}],
}


async def test_import_network_round_trip(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/import/network"
        body = json.loads(request.content)
        assert body == {
            "sources": [{"device": "iol", "content": "hostname r1\n", "name": "r1"}],
            "wiring": [["r1:Ethernet0/1", "r2:Ethernet0/1"]],
        }
        return httpx.Response(200, json=_NETWORK_IMPORT_PAYLOAD)

    async with make_client(handler) as client:
        result = await client.import_network(
            [ImportSource(device="iol", content="hostname r1\n", name="r1")],
            [["r1:Ethernet0/1", "r2:Ethernet0/1"]],
        )
    assert "provider: clab" in result.definition
    assert result.interface_map["r1"]["GigabitEthernet0/0/1"] == "Ethernet0/1"
    assert result.name_map == {"prod-r1": "prod_r1"}
    assert result.quarantine["r1"][0].reason == "auth"
    assert result.warnings[0].node == "r1"
    assert "imported/r1.quarantine.j2" in result.custom_config


async def test_import_network_error_slug(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "code": "duplicate_node",
                "message": "two sources resolve to node name 'r1'",
                "extras": {},
            },
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.import_network([ImportSource(device="iol", content="x\n")], [])
    assert excinfo.value.code == "duplicate_node"


async def test_import_node_parses(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/import/node"
        return httpx.Response(
            200,
            json={
                "fragment": "device: iol\nloopback:\n  ipv4: 10.0.0.1/32\n",
                "config": "{% raw %}\ninterface Ethernet0/1\n{% endraw %}\n",
                "interfaces": {"Ethernet0/1": "10.1.2.1/30", "Ethernet0/2": None},
                "quarantine": [],
                "warnings": [{"node": None, "message": "carried config keeps SOURCE names"}],
            },
        )

    async with make_client(handler) as client:
        result = await client.import_node("iol", "hostname r1\n")
    assert "device: iol" in result.fragment
    assert result.interfaces == {"Ethernet0/1": "10.1.2.1/30", "Ethernet0/2": None}
    assert result.warnings[0].node is None


async def test_config_diff_round_trip(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/labs/lab1/config-diff"
        body = json.loads(request.content)
        assert body == {
            "sources": [
                {"node": "r1", "content": "hostname r1\n", "interface_map": {"Gi0/1": "Et0/1"}}
            ]
        }
        return httpx.Response(
            200,
            json={
                "nodes": [
                    {
                        "node": "r1",
                        "matched": 12,
                        "missing": [" passive-interface Ethernet0/1"],
                        "extra": ["username admin secret 5 x"],
                        "quarantined": 3,
                    }
                ]
            },
        )

    async with make_client(handler) as client:
        report = await client.config_diff(
            "lab1",
            [
                DiffSource(
                    node="r1",
                    content="hostname r1\n",
                    interface_map={"Gi0/1": "Et0/1"},
                )
            ],
        )
    assert report.nodes[0].matched == 12
    assert report.nodes[0].missing == [" passive-interface Ethernet0/1"]
    assert report.nodes[0].quarantined == 3


async def test_suggest_wiring_parses(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/import/wiring-suggestion"
        assert json.loads(request.content) == {
            "sources": [{"device": "iol", "content": "hostname r1\n", "name": None}]
        }
        return httpx.Response(
            200,
            json={
                "wiring": [["r1:Ethernet0/1", "r2:Ethernet0/1"]],
                "warnings": [{"node": "r1", "message": "Ethernet0/4 is unnumbered"}],
            },
        )

    async with make_client(handler) as client:
        suggestion = await client.suggest_wiring(
            [ImportSource(device="iol", content="hostname r1\n")]
        )
    assert suggestion.wiring == [["r1:Ethernet0/1", "r2:Ethernet0/1"]]
    assert suggestion.warnings[0].node == "r1"


async def test_import_network_wiring_error_slug(make_client: ClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "code": "wiring_conflict",
                "message": "wiring entry 0: the wired interfaces sit in different subnets",
                "extras": {"entry": 0},
            },
        )

    async with make_client(handler) as client:
        with pytest.raises(TwinlabApiError) as excinfo:
            _ = await client.import_network(
                [ImportSource(device="iol", content="x\n")], [["r1:Et0/1", "r2:Et0/2"]]
            )
    assert excinfo.value.code == "wiring_conflict"
    assert excinfo.value.extras == {"entry": 0}
