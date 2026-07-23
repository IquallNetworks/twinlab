"""Permission and role definitions.

Permissions are code-defined constants; roles are stored as data (assignable per
user at runtime) but seeded from the mappings here on startup. Adding a
permission is a code change plus a re-seed — not a migration.
"""

from typing import Final

# Permission names, as stored in the `permissions` table.
LAB_CREATE: Final = "lab:create"
LAB_CONFIGURE: Final = "lab:configure"
LAB_DESTROY: Final = "lab:destroy"
LAB_READ: Final = "lab:read"
# Interactive shell/ssh into a node. Its own grant rather than a reuse of
# lab:configure: a console is full node control and worth gating separately.
LAB_TERMINAL: Final = "lab:terminal"
# Run a lab's test suites on demand. Its own grant, not a reuse of lab:read:
# validation executes the suites' declared commands on the nodes, which is more
# than reading. The automatic config-time run rides lab:configure (it is part of
# a configure), so this gates only the manual "run this suite now" path.
LAB_VALIDATE: Final = "lab:validate"
USER_MANAGE: Final = "user:manage"

ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    LAB_CREATE,
    LAB_CONFIGURE,
    LAB_DESTROY,
    LAB_READ,
    LAB_TERMINAL,
    LAB_VALIDATE,
    USER_MANAGE,
)

ADMIN_ROLE: Final = "admin"

# Role name -> permissions it grants.
ROLE_DEFINITIONS: Final[dict[str, tuple[str, ...]]] = {
    ADMIN_ROLE: ALL_PERMISSIONS,
    "operator": (LAB_CREATE, LAB_CONFIGURE, LAB_DESTROY, LAB_READ, LAB_TERMINAL, LAB_VALIDATE),
    "viewer": (LAB_READ,),
}
