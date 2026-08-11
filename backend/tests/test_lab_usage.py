"""Per-lab resource usage (delta 30).

The route body is exercised directly with stub upstreams; the DI and guards
above it are blackbox territory."""

from collections.abc import Callable
from typing import cast

import httpx

from twinlab_backend.api.labs import lab_usage
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.clab_api import ClabApiClient, ClabApiError, NodeInfo
from twinlab_backend.services.runner_client import RunnerClient


class _FakeClab:
    def __init__(self, nodes: tuple[tuple[str, str], ...], *, fail: bool = False) -> None:
        self._nodes = nodes
        self._fail = fail

    async def inspect(self, lab_name: str) -> Result[tuple[NodeInfo, ...], ClabApiError]:
        if self._fail:
            return Err(ClabApiError(status_code=502, message="clab down"))
        return Ok(
            tuple(
                NodeInfo(
                    node_name=node,
                    container_name=f"clab-{lab_name}-{node}",
                    image="img",
                    state=state,
                    ipv4_address="",
                )
                for node, state in self._nodes
            )
        )


def _runner(handler: Callable[[httpx.Request], httpx.Response]) -> RunnerClient:
    return RunnerClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://runner.test",
    )


async def test_running_nodes_carry_measures_and_stopped_ones_do_not() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/docker/stats"
        asked.extend(request.url.params.get_list("container"))
        return httpx.Response(
            200,
            json={
                "stats": [
                    {
                        "container": "clab-lab1-r1",
                        "cpu_percent": 12.5,
                        "memory_bytes": 1024,
                        "memory_limit_bytes": 2048,
                        "net_rx_bytes": 10,
                        "net_tx_bytes": 20,
                        "pids": 7,
                    }
                ]
            },
        )

    clab = _FakeClab((("r2", "stopped"), ("r1", "running")))
    usage = await lab_usage("lab1", cast(ClabApiClient, clab), _runner(handler))

    # Only the RUNNING container is asked about: a stopped one has nothing to
    # report, and the round trip would be wasted.
    assert asked == ["clab-lab1-r1"]
    assert usage.live is True
    # Sorted by node name, not by the order clab happened to list them.
    assert [node.node for node in usage.nodes] == ["r1", "r2"]

    r1, r2 = usage.nodes
    assert r1.cpu_percent == 12.5
    assert r1.memory_bytes == 1024
    assert r1.pids == 7
    # A stopped node is unmeasured, NOT idle.
    assert r2.state == "stopped"
    assert r2.cpu_percent is None
    assert r2.memory_bytes is None


async def test_undeployed_lab_is_not_live_rather_than_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("the runner must not be asked when there are no containers")

    clab = _FakeClab((), fail=True)
    usage = await lab_usage("lab1", cast(ClabApiClient, clab), _runner(handler))
    assert usage.live is False
    assert usage.nodes == []


async def test_runner_outage_keeps_the_node_rows_but_drops_live() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="runner down")

    clab = _FakeClab((("r1", "running"),))
    usage = await lab_usage("lab1", cast(ClabApiClient, clab), _runner(handler))
    # The nodes are known from clab either way; `live` reports whether the
    # MEASURES are real, so this reads as unmeasured rather than idle.
    assert usage.live is False
    assert [node.node for node in usage.nodes] == ["r1"]
    assert usage.nodes[0].cpu_percent is None
