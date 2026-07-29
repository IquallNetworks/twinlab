"""Public jump-host coordinates: how a user's ssh reaches the stack's jump.

The full connection recipe is client-side:
``ssh -o ProxyJump={user}@{host}:{port} <node-user>@<node-mgmt-ip>``.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.deps import SettingsDep

router = APIRouter(tags=["ssh-access"])

# The system account every jump connection authenticates as. Fixed by the jump
# image (which key is offered selects the Twinlab identity, not the username).
_JUMP_USER = "jump"


class SshAccessOut(BaseModel):
    enabled: bool
    host: str | None
    port: int | None
    user: str | None


@router.get("/ssh-access")
async def get_ssh_access(_user: CurrentUserDep, settings: SettingsDep) -> SshAccessOut:
    address = settings.ssh_jump_address
    if not address:
        return SshAccessOut(enabled=False, host=None, port=None, user=None)
    host, _, port = address.rpartition(":")  # shape validated at settings load
    return SshAccessOut(enabled=True, host=host, port=int(port), user=_JUMP_USER)
