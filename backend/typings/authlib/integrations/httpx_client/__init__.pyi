from types import TracebackType
from typing import Literal, Self

import httpx2

class AsyncOAuth2Client:
    def __init__(
        self,
        client_id: str,
        client_secret: str | None = ...,
        token_endpoint_auth_method: str | None = ...,
        *,
        code_challenge_method: Literal["S256"] | None = ...,
        timeout: float = ...,
        transport: httpx2.AsyncBaseTransport | None = ...,
    ) -> None: ...
    async def fetch_token(
        self,
        url: str,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, object]: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
