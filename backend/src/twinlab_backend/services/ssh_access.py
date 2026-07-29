"""Jump-host authorization: an offered key fingerprint -> authorized_keys text.

The fail-safe invariant lives here: sshd treats a key line WITHOUT permitopen
options as "forward anywhere", so an empty permitted-node set must produce NO
line at all (empty answer -> authentication denied) — never a permitopen-less
line. The renderer enforces it; keep it that way.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth import ssh_keys
from twinlab_backend.auth.service import permitted_lab_names
from twinlab_backend.db.models import Lab
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.clab_api import ClabApiClient, ClabApiError


def render_authorized_keys_line(
    algorithm: str, key_b64: str, username: str, node_ips: list[str]
) -> str:
    """One forwarding-only authorized_keys line restricted to the given node
    addresses (all TCP ports each — the authorization boundary is the node).
    Returns "" for an empty node list: sshd then sees no matching key and
    denies authentication, which is the ONLY safe rendering of "nothing
    permitted" (see module docstring)."""
    if not node_ips:
        return ""
    options = ["restrict", "port-forwarding"] + [f'permitopen="{ip}:*"' for ip in node_ips]
    return f"{','.join(options)} {algorithm} {key_b64} twinlab:{username}"


async def authorized_keys_for(
    session: AsyncSession, clab: ClabApiClient, fingerprint: str
) -> Result[str, ClabApiError]:
    """The authorized_keys answer for an offered fingerprint: one line scoped
    to the live nodes of labs where the key's owner holds lab:terminal, or ""
    (deny). Err only on a clab-api failure — the route maps it to a 5xx so the
    jump's lookup script exits non-zero and sshd fails closed, rather than a
    healthy-looking denial of a valid key."""
    key = await ssh_keys.resolve_fingerprint(session, fingerprint)
    if key is None:
        return Ok("")
    lab_names = await permitted_lab_names(session, key.user, perms.LAB_TERMINAL)
    if lab_names is None:
        # Global lab:terminal = every Twinlab lab — but only Twinlab's: the
        # clab inventory may contain foreign labs deployed outside Twinlab.
        rows = await session.scalars(select(Lab.name).where(Lab.deleted_at.is_(None)))
        lab_names = set(rows.all())
    if not lab_names:
        return Ok("")
    inventory = await clab.list_labs()
    if isinstance(inventory, Err):
        return inventory
    node_ips = sorted(
        node.ipv4_address.split("/", 1)[0]
        for lab_name, nodes in inventory.value.items()
        if lab_name in lab_names
        for node in nodes
        if node.ipv4_address
    )
    return Ok(render_authorized_keys_line(key.algorithm, key.key_b64, key.user.username, node_ips))
