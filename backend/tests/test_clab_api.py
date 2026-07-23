import json
from collections.abc import Callable

import httpx

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.clab_api import ClabApiClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ClabApiClient:
    return ClabApiClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://clab.test",
        username="u",
        password="p",
    )


async def test_destroy_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/labs/tmp1"
        assert request.url.params.get("cleanup") == "true"  # artifacts removed too
        assert request.headers["Authorization"] == "Bearer t"
        return httpx.Response(200, text="destroyed tmp1")

    result = await _client(handler).destroy("tmp1")
    assert isinstance(result, Ok), result
    assert result.value == "destroyed tmp1"


async def test_destroy_not_found_carries_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(404, text="lab not found")

    result = await _client(handler).destroy("missing")
    assert isinstance(result, Err)
    assert result.error.status_code == 404


_NODE = {
    "nodeName": "r1",
    "name": "clab-tmp1-r1",
    "image": "ghcr.io/sysoleg/vyos-container",
    "state": "running",
    "ipv4_address": "192.168.121.101/24",
}


async def test_deploy_parses_lab_name_and_nodes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.url.path == "/api/v1/labs"
        # The server keys the deploy response by lab name -> node list.
        return httpx.Response(
            200, json={"tmp1": [_NODE, {**_NODE, "nodeName": "r2", "name": "clab-tmp1-r2"}]}
        )

    result = await _client(handler).deploy({"name": "tmp1"})
    assert isinstance(result, Ok), result
    assert result.value.name == "tmp1"
    assert [n.node_name for n in result.value.nodes] == ["r1", "r2"]
    assert result.value.nodes[0].container_name == "clab-tmp1-r1"
    assert result.value.nodes[0].ipv4_address == "192.168.121.101/24"


async def test_node_without_mgmt_ip_defaults_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        node = {k: v for k, v in _NODE.items() if k != "ipv4_address"}
        return httpx.Response(200, json=[node])

    result = await _client(handler).inspect("tmp1")
    assert isinstance(result, Ok), result
    assert result.value[0].ipv4_address == ""


async def test_list_labs_maps_by_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "GET"
        assert request.url.path == "/api/v1/labs"
        return httpx.Response(200, json={"tmp1": [_NODE], "tmp2": []})

    result = await _client(handler).list_labs()
    assert isinstance(result, Ok), result
    assert set(result.value) == {"tmp1", "tmp2"}
    assert result.value["tmp1"][0].node_name == "r1"
    assert result.value["tmp2"] == ()


async def test_inspect_parses_node_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "GET"
        assert request.url.path == "/api/v1/labs/tmp1"
        return httpx.Response(
            200, json=[_NODE, {**_NODE, "nodeName": "r2", "name": "clab-tmp1-r2"}]
        )

    result = await _client(handler).inspect("tmp1")
    assert isinstance(result, Ok), result
    assert [n.node_name for n in result.value] == ["r1", "r2"]


async def test_inspect_not_found_carries_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(404, text="lab not found")

    result = await _client(handler).inspect("missing")
    assert isinstance(result, Err)
    assert result.error.status_code == 404


async def test_exec_filters_by_container_and_returns_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs/tmp1/exec"
        # nodeFilter scopes to one node and takes the container name.
        assert request.url.params.get("nodeFilter") == "clab-tmp1-r1"
        assert json.loads(request.content) == {"command": "show version"}
        return httpx.Response(
            200,
            json={
                "clab-tmp1-r1": [
                    {
                        "cmd": ["sh", "-c", "show version"],
                        "return-code": 0,
                        "stdout": "v1",
                        "stderr": "",
                    }
                ]
            },
        )

    result = await _client(handler).exec("tmp1", "clab-tmp1-r1", "show version")
    assert isinstance(result, Ok), result
    assert result.value.stdout == "v1"
    assert result.value.return_code == 0


async def test_exec_empty_result_is_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        # No node matched the filter -> empty map.
        return httpx.Response(200, json={})

    result = await _client(handler).exec("tmp1", "clab-tmp1-r1", "show version")
    assert isinstance(result, Err)
    assert "no result" in result.error.message


async def test_deploy_reconfigure_sets_query_param() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.url.params.get("reconfigure") == "true"
        return httpx.Response(200, json={"tmp1": [_NODE]})

    result = await _client(handler).deploy({"name": "tmp1"}, reconfigure=True)
    assert isinstance(result, Ok), result
    assert result.value.name == "tmp1"


async def test_node_action_returns_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs/tmp1/nodes/r1/restart"
        return httpx.Response(200, json={"message": "node r1 restarted"})

    result = await _client(handler).node_action("tmp1", "r1", "restart")
    assert isinstance(result, Ok), result
    assert result.value == "node r1 restarted"


async def test_node_action_pause_targets_pause_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs/tmp1/nodes/r1/pause"
        return httpx.Response(200, json={"message": "node r1 paused"})

    result = await _client(handler).node_action("tmp1", "r1", "pause")
    assert isinstance(result, Ok), result
    assert result.value == "node r1 paused"


async def test_lab_action_returns_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.url.path == "/api/v1/labs/tmp1/stop"
        return httpx.Response(200, json={"message": "lab tmp1 stopped"})

    result = await _client(handler).lab_action("tmp1", "stop")
    assert isinstance(result, Ok), result
    assert result.value == "lab tmp1 stopped"


async def test_node_logs_parses_container_and_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        # clab-api's logs endpoint matches the full container name, not the short
        # node name; the caller resolves it, so the client puts it in the path.
        assert request.url.path == "/api/v1/labs/tmp1/nodes/clab-tmp1-r1/logs"
        assert request.url.params.get("tail") == "100"
        return httpx.Response(200, json={"containerName": "clab-tmp1-r1", "logs": "boot ok\n"})

    result = await _client(handler).node_logs("tmp1", "clab-tmp1-r1", tail="100")
    assert isinstance(result, Ok), result
    assert result.value.container_name == "clab-tmp1-r1"
    assert result.value.logs == "boot ok\n"


async def test_interfaces_parses_per_node_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.url.path == "/api/v1/labs/tmp1/interfaces"
        return httpx.Response(
            200,
            json=[
                {
                    "name": "r1",
                    "interfaces": [
                        {
                            "name": "eth1",
                            "alias": "",
                            "ifindex": 2,
                            "mac": "aa:bb:cc:dd:ee:ff",
                            "mtu": 1500,
                            "state": "up",
                            "type": "veth",
                        }
                    ],
                }
            ],
        )

    result = await _client(handler).interfaces("tmp1")
    assert isinstance(result, Ok), result
    assert len(result.value) == 1
    node = result.value[0]
    assert node.node_name == "r1"
    assert node.interfaces[0].name == "eth1"
    assert node.interfaces[0].kind == "veth"  # clab-api's `type`, renamed


async def test_save_config_parses_message_and_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs/tmp1/save"
        return httpx.Response(200, json={"message": "saved", "output": "r1: ok"})

    result = await _client(handler).save_config("tmp1")
    assert isinstance(result, Ok), result
    assert result.value.message == "saved"
    assert result.value.output == "r1: ok"


# NDJSON body mirroring clab-api's /events: a lab event, one with no lab (dropped),
# a malformed line (dropped), and another lab event.
_EVENTS_BODY = (
    '{"timestamp":"t1","action":"start","attributes":{"containerlab":"lab-ev","clab-node-name":"r1"}}\n'
    '{"timestamp":"t2","action":"stop","attributes":{"clab-node-name":"r1"}}\n'
    "not json\n"
    '{"timestamp":"t3","action":"destroy","attributes":{"containerlab":"lab-ev","clab-node-name":"r1"}}\n'
)


async def test_stream_events_yields_only_lab_scoped_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.url.path == "/api/v1/events"
        return httpx.Response(200, content=_EVENTS_BODY.encode())

    events = [event async for event in _client(handler).stream_events()]
    # The no-lab and malformed lines are dropped; the two lab events survive in order.
    assert [(e.lab, e.node, e.action) for e in events] == [
        ("lab-ev", "r1", "start"),
        ("lab-ev", "r1", "destroy"),
    ]


async def test_stream_events_ends_quietly_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(500, text="boom")

    assert [event async for event in _client(handler).stream_events()] == []


async def test_set_netem_sends_only_provided_impairments() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/tools/netem/set"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": "netem set"})

    result = await _client(handler).set_netem(
        "clab-tmp1-r1", "eth1", delay="50ms", jitter=None, loss=1.5, rate=None, corruption=None
    )
    assert isinstance(result, Ok), result
    assert result.value == "netem set"
    # Omitted impairments (jitter/rate/corruption) are left out entirely, not zeroed.
    assert captured == {
        "containerName": "clab-tmp1-r1",
        "interface": "eth1",
        "delay": "50ms",
        "loss": 1.5,
    }


async def test_show_netem_flattens_the_container_map() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "GET"
        assert request.url.path == "/api/v1/tools/netem/show"
        assert request.url.params.get("containerName") == "clab-tmp1-r1"
        return httpx.Response(
            200,
            json={
                "clab-tmp1-r1": [
                    {
                        # show decorates the name with its link; we strip to "eth1"
                        "interface": "eth1 (r1 -> r2)",
                        "delay": "50ms",
                        "jitter": "",
                        "packet_loss": 1.5,
                        "rate": 0,
                        # corruption omitted: older servers don't report it → 0.0
                    }
                ]
            },
        )

    result = await _client(handler).show_netem("clab-tmp1-r1")
    assert isinstance(result, Ok), result
    assert len(result.value) == 1
    impairment = result.value[0]
    assert impairment.interface == "eth1"  # link annotation stripped
    assert impairment.delay == "50ms"
    assert impairment.loss == 1.5  # parsed from the packet_loss key
    assert impairment.corruption == 0.0


async def test_reset_netem_posts_container_and_interface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/tools/netem/reset"
        assert json.loads(request.content) == {
            "containerName": "clab-tmp1-r1",
            "interface": "eth1",
        }
        return httpx.Response(200, json={"message": "netem reset"})

    result = await _client(handler).reset_netem("clab-tmp1-r1", "eth1")
    assert isinstance(result, Ok), result
    assert result.value == "netem reset"


async def test_create_terminal_session_sends_request_and_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "POST"
        assert request.url.path == "/api/v1/labs/tmp1/nodes/r1/terminal-sessions"
        assert request.headers["Authorization"] == "Bearer t"
        # No sshUsername key when unset — leaves clab-api's own default in place.
        assert json.loads(request.content) == {"protocol": "ssh", "cols": 120, "rows": 30}
        # clab-api answers with a fuller TerminalSessionInfo; only sessionId is used.
        return httpx.Response(200, json={"sessionId": "sess-abc", "state": "ready"})

    result = await _client(handler).create_terminal_session(
        "tmp1", "r1", protocol="ssh", cols=120, rows=30
    )
    assert isinstance(result, Ok), result
    assert result.value == "sess-abc"


async def test_create_terminal_session_includes_ssh_username_when_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert json.loads(request.content) == {
            "protocol": "ssh",
            "cols": 80,
            "rows": 24,
            "sshUsername": "vyos",
        }
        return httpx.Response(200, json={"sessionId": "sess-xyz"})

    result = await _client(handler).create_terminal_session(
        "tmp1", "r1", protocol="ssh", cols=80, rows=24, ssh_username="vyos"
    )
    assert isinstance(result, Ok), result
    assert result.value == "sess-xyz"


async def test_create_terminal_session_carries_status_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(404, text="node not found")

    result = await _client(handler).create_terminal_session(
        "tmp1", "missing", protocol="shell", cols=80, rows=24
    )
    assert isinstance(result, Err)
    assert result.error.status_code == 404


async def test_delete_terminal_session_posts_delete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/terminal-sessions/sess-abc"
        return httpx.Response(200, json={"message": "closed"})

    result = await _client(handler).delete_terminal_session("sess-abc")
    assert isinstance(result, Ok), result


async def test_open_terminal_stream_errs_when_login_fails() -> None:
    # The WS stream needs a JWT first; a login failure short-circuits before any
    # WebSocket connect is attempted, so no real socket is opened here.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login"
        return httpx.Response(401, text="bad creds")

    result = await _client(handler).open_terminal_stream("sess-abc")
    assert isinstance(result, Err)
    assert result.error.status_code == 401
