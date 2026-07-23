"""error_from_response: the target envelope plus the four legacy shapes."""

import httpx

from twinlab_client.errors import error_from_response


def test_target_envelope() -> None:
    response = httpx.Response(
        409,
        json={"code": "lab_exists", "message": "lab already exists", "extras": {"name": "l1"}},
    )
    error = error_from_response(response)
    assert error.status_code == 409
    assert error.code == "lab_exists"
    assert error.message == "lab already exists"
    assert error.extras == {"name": "l1"}


def test_legacy_bare_string_detail() -> None:
    error = error_from_response(httpx.Response(401, json={"detail": "invalid credentials"}))
    assert error.code == "unknown"
    assert error.message == "invalid credentials"
    assert error.extras["raw"] == {"detail": "invalid credentials"}


def test_legacy_fastapi_validation_list() -> None:
    detail = [{"loc": ["body", "name"], "msg": "field required", "type": "missing"}]
    error = error_from_response(httpx.Response(422, json={"detail": detail}))
    assert error.code == "validation_error"
    assert error.message == "request validation failed"
    assert error.extras["errors"] == detail


def test_legacy_stage_shape() -> None:
    body = {"detail": {"stage": "netlab_invalid", "message": "bad topology", "stderr": "boom"}}
    error = error_from_response(httpx.Response(422, json=body))
    assert error.code == "netlab_invalid"
    assert error.message == "bad topology"
    assert error.extras["raw"] == body


def test_legacy_reason_shape() -> None:
    body = {"detail": {"reason": "username_taken", "detail": "user 'x' exists"}}
    error = error_from_response(httpx.Response(409, json=body))
    assert error.code == "username_taken"
    assert error.message == "user 'x' exists"
    assert error.extras["raw"] == body


def test_non_json_body() -> None:
    error = error_from_response(httpx.Response(502, text="Bad Gateway from nginx"))
    assert error.code == "unknown"
    assert error.message == "Bad Gateway from nginx"
    assert error.extras == {}


def test_str() -> None:
    error = error_from_response(httpx.Response(404, json={"detail": "lab not found"}))
    assert str(error) == "HTTP 404 [unknown]: lab not found"
