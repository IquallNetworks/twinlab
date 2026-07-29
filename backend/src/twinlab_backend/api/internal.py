"""Internal endpoints, consumed by sibling services of the compose stack.

Registered WITHOUT the /api/v1 prefix: the frontend proxy forwards only
/api/v1, so /internal is unreachable from outside even before the token check
(the backend publishes no host port; the token is defense in depth).
"""

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from twinlab_backend.api_errors import ApiError
from twinlab_backend.deps import ClabClientDep, SessionDep, SettingsDep
from twinlab_backend.result import Err
from twinlab_backend.services import ssh_access

router = APIRouter(prefix="/internal", tags=["internal"])


async def _jump_authorized(request: Request, settings: SettingsDep) -> None:
    # No token configured = the jump feature is off; the route hides entirely.
    if settings.ssh_jump_token is None:
        raise ApiError(404, "not_found", "not found")
    offered = request.headers.get("X-Jump-Token", "")
    if not hmac.compare_digest(offered, settings.ssh_jump_token.get_secret_value()):
        raise ApiError(401, "not_authenticated", "invalid jump token")


@router.get("/ssh/authorized-keys", dependencies=[Depends(_jump_authorized)])
async def ssh_authorized_keys(
    fingerprint: str, db: SessionDep, clab: ClabClientDep
) -> PlainTextResponse:
    """sshd's AuthorizedKeysCommand lookup: the offered key's fingerprint in,
    zero or one authorized_keys lines out. An empty body means "deny" — sshd
    finds no matching key. Unknown fingerprints are routine (agents offer
    every key they hold)."""
    answer = await ssh_access.authorized_keys_for(db, clab, fingerprint)
    if isinstance(answer, Err):
        # 5xx -> the lookup script exits non-zero -> sshd fails CLOSED.
        raise ApiError(502, "clab_api_error", answer.error.message)
    return PlainTextResponse(answer.value)
