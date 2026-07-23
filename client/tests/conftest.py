"""Shared fixtures: a TwinlabClient wired to an httpx.MockTransport."""

from collections.abc import Callable

import httpx
import pytest

from twinlab_client import TwinlabClient

Handler = Callable[[httpx.Request], httpx.Response]

ClientFactory = Callable[[Handler], TwinlabClient]


@pytest.fixture
def make_client() -> ClientFactory:
    def factory(handler: Handler) -> TwinlabClient:
        return TwinlabClient("http://testserver", transport=httpx.MockTransport(handler))

    return factory
