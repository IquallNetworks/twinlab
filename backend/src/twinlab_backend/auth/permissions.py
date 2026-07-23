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
USER_MANAGE: Final = "user:manage"

ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    LAB_CREATE,
    LAB_CONFIGURE,
    LAB_DESTROY,
    LAB_READ,
    USER_MANAGE,
)

ADMIN_ROLE: Final = "admin"

# Role name -> permissions it grants.
ROLE_DEFINITIONS: Final[dict[str, tuple[str, ...]]] = {
    ADMIN_ROLE: ALL_PERMISSIONS,
    "operator": (LAB_CREATE, LAB_CONFIGURE, LAB_DESTROY, LAB_READ),
    "viewer": (LAB_READ,),
}
