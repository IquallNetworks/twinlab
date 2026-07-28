"""The API's single error envelope (contract delta 1).

Every non-2xx response is ``{"code": <slug>, "message": <human>, "extras": {...}}``.
Our code raises `ApiError` — the one exception the handlers below translate to
that envelope; framework-raised errors (request validation, unknown routes,
wrong methods) are mapped into the same shape so no error ever leaves in
another format.

`code` is a stable slug for programmatic matching (e.g. "lab_not_found",
"permission_denied", "netlab_invalid"); `extras` carries the endpoint-specific
payload (netlab stderr, per-node config results, field errors under "errors").
"""

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        extras: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        # Most raises carry no endpoint payload; None keeps those sites clean.
        self.extras: dict[str, object] = extras if extras is not None else {}


def _envelope(
    status_code: int,
    code: str,
    message: str,
    extras: dict[str, object],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "extras": extras},
        headers=headers,
    )


# Framework-raised HTTPExceptions we still expect after the sweep: routing misses.
_FRAMEWORK_CODES = {404: "not_found", 405: "method_not_allowed"}


# Handlers take the widened `Exception` starlette's ExceptionHandler type
# demands (the parameter is contravariant); each is registered for exactly one
# type, so the isinstance assertion is a guarantee, not a check.


async def _handle_api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _envelope(exc.status_code, exc.code, exc.message, exc.extras)


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors: object = jsonable_encoder(exc.errors())
    return _envelope(422, "validation_error", "request validation failed", {"errors": errors})


async def _handle_http_error(_request: Request, exc: Exception) -> JSONResponse:
    # Our code never raises HTTPException (it raises ApiError); this covers the
    # framework's own — unknown route (404), wrong method (405), ... — so even
    # those wear the envelope. `detail` is a plain string there.
    assert isinstance(exc, StarletteHTTPException)
    code = _FRAMEWORK_CODES.get(exc.status_code, "http_error")
    return _envelope(exc.status_code, code, str(exc.detail), {}, headers=exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
