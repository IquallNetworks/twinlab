"""Suite-wide constants, config shape, and fixture-factory types.

Lives outside conftest because pytest's rootdir import mode doesn't make
`conftest` importable as a module.
"""

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from twinlab_client import GroupSummary, LabDetail, TwinlabClient, UserSummary


@dataclass(frozen=True, slots=True)
class SuiteConfig:
    base_url: str
    admin_username: str
    admin_password: str


# Factory fixtures (see conftest): created resources are cleaned up best-effort
# at teardown, tests must not depend on cleanup having worked.
UserClientFactory = Callable[[set[str] | None], Awaitable[tuple[UserSummary, TwinlabClient]]]
LabFactory = Callable[[TwinlabClient | None], Awaitable[LabDetail]]
GroupFactory = Callable[[], Awaitable[GroupSummary]]

# Randomized per run: cleanup is best-effort on a live stack, and a leaked
# bb-* account must not carry a known (committed) password.
DEFAULT_PASSWORD: Final = f"bb-{secrets.token_urlsafe(12)}"
ALTERNATE_PASSWORD: Final = f"bb-{secrets.token_urlsafe(12)}"  # for password-change tests

# Every user carries an email (unique, case-insensitively) and a display name
# (delta 33). Suite users get an address under the reserved `.test` TLD derived
# from their unique name, so they never collide and never reach anyone.
BB_EMAIL_DOMAIN: Final = "bb.test"


async def create_bb_user(
    admin: TwinlabClient,
    username: str,
    *,
    password: str = DEFAULT_PASSWORD,
    roles: set[str] | None = None,
) -> UserSummary:
    created = await admin.create_user(
        username,
        f"{username}@{BB_EMAIL_DOMAIN}",
        f"Blackbox {username}",
        password=password,
        roles=roles,
    )
    return created.user


# The seven lab-scoped permissions; a lab owner holds exactly this set implicitly.
LAB_SCOPED_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        "lab:read",
        "lab:edit",
        "lab:configure",
        "lab:validate",
        "lab:terminal",
        "lab:destroy",
        "lab:grant",
    }
)

# A minimal, fast-deploying definition: two plain linux containers, one link.
# Every node's device is stated (a Twinlab domain rule — never defaulted).
LINUX_LAB_DEFINITION: Final = """\
provider: clab
defaults.device: linux
nodes: [n1, n2]
links: [n1-n2]
"""

# Groups, including a NESTED one (delta 32): `core` names `inner`, not its
# members, because that is what netlab's expanded topology actually contains —
# the flattening is Twinlab's. Linux nodes only, so this never needs a deploy.
GROUPED_LAB_DEFINITION: Final = """\
provider: clab
defaults.device: linux
groups:
  inner:
    members: [n1, n2]
  core:
    members: [inner, n3]
nodes: [n1, n2, n3]
links: [n1-n2, n2-n3]
"""

# Two DIFFERENT NOSes in one topology, both on the docker-exec transport, so a
# mixed-platform deploy stays cheap. VyOS and bird speak plain OSPFv2 to each
# other; the linux host is the third device class.
#
# Deliberately NOT frr here: netlab's FRR initial script installs gnupg+curl,
# which the official FRR image lacks, so its config push needs working egress
# and DNS FROM THE LAB NODE — a test must not depend on that.
MIXED_NOS_LAB_DEFINITION: Final = """\
provider: clab
module: [ospf]
nodes:
  v1:
    device: vyos
  b1:
    device: bird
  h1:
    device: linux
links:
- v1-b1
- v1-h1
"""

# A multi-access (3-endpoint) segment: netlab's clab provider references a
# host bridge for it, so deploying exercises the hostprep path end-to-end.
LAN_LAB_DEFINITION: Final = """\
provider: clab
defaults.device: linux
nodes: [n1, n2, n3]
links:
- [n1, n2, n3]
"""

# Valid YAML that netlab must reject (unknown device) -> 422 on authoring.
NETLAB_INVALID_DEFINITION: Final = """\
provider: clab
defaults.device: bb-not-a-device
nodes: [n1]
"""

# Not parseable as YAML at all -> 422 on authoring.
NOT_YAML_DEFINITION: Final = "nodes: [unclosed\n"
