"""Shared fixtures: a TwinlabClient wired to an httpx2.MockTransport."""

from collections.abc import Callable

import httpx2
import pytest

from twinlab_client import TwinlabClient

Handler = Callable[[httpx2.Request], httpx2.Response]

ClientFactory = Callable[[Handler], TwinlabClient]


@pytest.fixture
def make_client() -> ClientFactory:
    def factory(handler: Handler) -> TwinlabClient:
        return TwinlabClient("http://testserver", transport=httpx2.MockTransport(handler))

    return factory
