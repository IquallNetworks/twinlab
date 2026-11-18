"""Delta 38: lab reads degrade to the stored record when clab-api is slow or
down, instead of failing, and say so with `live`."""

from datetime import UTC, datetime
from typing import cast

from twinlab_backend.api.labs import lab_summary, live_detail
from twinlab_backend.db.models import Lab
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.clab_api import ClabApiClient, ClabApiError, NodeInfo

_NODE = NodeInfo(
    node_name="r1", container_name="clab-lab1-r1", image="i", state="running", ipv4_address=""
)


def _lab() -> Lab:
    lab = Lab(name="lab1", definition="name: lab1\n", status="deployed")
    lab.owner = None
    lab.created_at = datetime(2026, 11, 18, tzinfo=UTC)
    lab.updated_at = lab.created_at
    lab.template_published = False
    return lab


class _FakeClab:
    def __init__(self, result: Result[tuple[NodeInfo, ...], ClabApiError]) -> None:
        self.result = result
        self.timeouts: list[float | None] = []

    async def inspect(
        self, lab_name: str, *, timeout: float | None = None
    ) -> Result[tuple[NodeInfo, ...], ClabApiError]:
        self.timeouts.append(timeout)
        return self.result


async def _detail(result: Result[tuple[NodeInfo, ...], ClabApiError]) -> tuple[bool, int, float]:
    fake = _FakeClab(result)
    detail = await live_detail(_lab(), cast("ClabApiClient", fake), ["lab:read"])
    (timeout,) = fake.timeouts
    assert timeout is not None
    return detail.live, len(detail.nodes), timeout


async def test_a_read_detail_is_live() -> None:
    live, nodes, timeout = await _detail(Ok((_NODE,)))
    assert (live, nodes) == (True, 1)
    # Bounded well under the client's 30 s, so a page never hangs behind
    # clab-api's lock for long.
    assert timeout <= 10


async def test_an_undeployed_lab_has_no_nodes_and_that_is_known() -> None:
    assert (await _detail(Err(ClabApiError("no lab", 404))))[:2] == (True, 0)


async def test_a_slow_or_failing_clab_api_degrades_instead_of_failing() -> None:
    # status None: a transport failure, the timeout behind the lock included.
    for status in (None, 500, 502):
        assert (await _detail(Err(ClabApiError("timed out", status))))[:2] == (False, 0)


def test_the_list_marks_unread_counts_not_live() -> None:
    lab = _lab()
    read = lab_summary(lab, {"lab1": (_NODE,)}, [])
    unread = lab_summary(lab, None, [])
    assert (read.live, read.nodes) == (True, 1)
    assert (unread.live, unread.nodes) == (False, 0)
