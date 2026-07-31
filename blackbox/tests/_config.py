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
