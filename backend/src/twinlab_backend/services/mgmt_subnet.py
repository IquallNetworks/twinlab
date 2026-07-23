"""Management-subnet allocation.

netlab defaults every lab's management network to 192.168.121.0/24, so two labs
up at once collide. We carve a configured pool into /24s and hand each lab a
distinct one. Allocation avoids every subnet already recorded against a lab
(regardless of status) — records are never hard-deleted, so a destroyed lab
keeps its subnet and a later redeploy can't clash with a lab deployed meanwhile.

Pure and side-effect-free: the caller supplies the pool and the in-use set and
persists the result. `ipaddress` parsing is the boundary; outcomes are values.
"""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from twinlab_backend.result import Err, Ok, Result

# Each lab gets a full /24 — matching netlab's own mgmt default and leaving room
# for any realistic node count without sub-allocating.
_LAB_PREFIX = 24


@dataclass(frozen=True, slots=True)
class MgmtSubnetError:
    reason: str  # "invalid_pool" | "exhausted"
    message: str


def allocate_subnet(pool: str, used: Iterable[str]) -> Result[str, MgmtSubnetError]:
    """Return the lowest-ordered /24 in `pool` not present in `used`, as a CIDR
    string (e.g. "10.77.3.0/24"). Errors if the pool is unparseable, smaller than
    a /24, or fully consumed."""
    try:
        network = ipaddress.ip_network(pool, strict=False)
    except ValueError as exc:
        return Err(MgmtSubnetError("invalid_pool", f"invalid mgmt subnet pool '{pool}': {exc}"))
    if network.prefixlen > _LAB_PREFIX:
        return Err(
            MgmtSubnetError(
                "invalid_pool", f"mgmt subnet pool '{pool}' is smaller than a /{_LAB_PREFIX}"
            )
        )

    used_set = set(used)
    for candidate in network.subnets(new_prefix=_LAB_PREFIX):
        cidr = str(candidate)
        if cidr not in used_set:
            return Ok(cidr)
    return Err(MgmtSubnetError("exhausted", f"mgmt subnet pool '{pool}' is exhausted"))
