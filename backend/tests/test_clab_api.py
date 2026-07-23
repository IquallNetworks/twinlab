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
        assert request.url.path == "/api/v1/labs/tmp1/nodes/r1/logs"
        assert request.url.params.get("tail") == "100"
        return httpx.Response(200, json={"containerName": "clab-tmp1-r1", "logs": "boot ok\n"})

    result = await _client(handler).node_logs("tmp1", "r1", tail="100")
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
