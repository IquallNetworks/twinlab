from twinlab_backend.result import Err, Ok
from twinlab_backend.services.mgmt_subnet import allocate_subnet


def test_allocate_returns_first_subnet_when_none_used() -> None:
    result = allocate_subnet("10.77.0.0/16", set())
    assert isinstance(result, Ok), result
    assert result.value == "10.77.0.0/24"


def test_allocate_skips_used_subnets() -> None:
    used = {"10.77.0.0/24", "10.77.1.0/24"}
    result = allocate_subnet("10.77.0.0/16", used)
    assert isinstance(result, Ok), result
    assert result.value == "10.77.2.0/24"


def test_allocate_exhausted_when_pool_is_one_used_subnet() -> None:
    result = allocate_subnet("10.77.5.0/24", {"10.77.5.0/24"})
    assert isinstance(result, Err)
    assert result.error.reason == "exhausted"


def test_allocate_rejects_pool_smaller_than_a_24() -> None:
    result = allocate_subnet("10.77.5.0/25", set())
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_pool"


def test_allocate_rejects_unparseable_pool() -> None:
    result = allocate_subnet("not-a-cidr", set())
    assert isinstance(result, Err)
    assert result.error.reason == "invalid_pool"


def test_allocate_pool_that_is_exactly_one_24() -> None:
    result = allocate_subnet("192.168.50.0/24", set())
    assert isinstance(result, Ok), result
    assert result.value == "192.168.50.0/24"
