"""Client error types and the wire-error → exception mapping."""

from dataclasses import dataclass
from typing import cast

import httpx2


# Deliberately NOT frozen: re-raising through a context manager assigns
# `exc.__traceback__` at Python level (contextlib), which a frozen dataclass's
# __setattr__ rejects. Exceptions must stay mutable.
@dataclass(slots=True)
class TwinlabApiError(Exception):
    """Any non-2xx response.

    The v1.0 wire serves one envelope for every error:

        {"code": "<machine slug>", "message": "<human>", "extras": {...}}

    `code` is a stable slug for programmatic matching (e.g. "lab_not_found",
    "netlab_invalid", "permission_denied"); `extras` is the endpoint-specific
    payload (netlab stderr, per-node config results, field errors, ...).

    Until the backend rework lands the envelope, the fields are filled
    best-effort from the current wire's four `detail` shapes (`code` from
    `stage`/`reason` when present, else "unknown"; the raw body is kept in
    `extras["raw"]`).
    """

    status_code: int
    code: str
    message: str
    extras: dict[str, object]

    def __str__(self) -> str:
        return f"HTTP {self.status_code} [{self.code}]: {self.message}"


class TwinlabProtocolError(Exception):
    """A 2xx body (or stream frame) that does not match the v1.0 contract."""

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"{where}: {detail}")
        self.where = where
        self.detail = detail


def error_from_response(response: httpx2.Response) -> TwinlabApiError:
    """Map a non-2xx response to `TwinlabApiError` (see the class docstring
    for the envelope and the best-effort legacy mapping)."""
    status = response.status_code
    try:
        body: object = response.json()
    except ValueError:
        text = response.text.strip()
        return TwinlabApiError(status, "unknown", text or response.reason_phrase, {})

    if isinstance(body, dict):
        obj = cast("dict[str, object]", body)
        code = obj.get("code")
        message = obj.get("message")
        if isinstance(code, str) and isinstance(message, str):
            extras_value = obj.get("extras")
            extras = (
                cast("dict[str, object]", extras_value) if isinstance(extras_value, dict) else {}
            )
            return TwinlabApiError(status, code, message, extras)

        detail = obj.get("detail")
        if isinstance(detail, str):
            return TwinlabApiError(status, "unknown", detail, {"raw": body})
        if isinstance(detail, list):
            errors = cast("list[object]", detail)
            return TwinlabApiError(
                status, "validation_error", "request validation failed", {"errors": errors}
            )
        if isinstance(detail, dict):
            detail_obj = cast("dict[str, object]", detail)
            stage = detail_obj.get("stage")
            if isinstance(stage, str):
                stage_message = detail_obj.get("message")
                return TwinlabApiError(
                    status,
                    stage,
                    stage_message if isinstance(stage_message, str) else response.reason_phrase,
                    {"raw": body},
                )
            reason = detail_obj.get("reason")
            if isinstance(reason, str):
                reason_detail = detail_obj.get("detail")
                return TwinlabApiError(
                    status,
                    reason,
                    reason_detail if isinstance(reason_detail, str) else response.reason_phrase,
                    {"raw": body},
                )

    return TwinlabApiError(status, "unknown", response.reason_phrase, {"raw": body})
