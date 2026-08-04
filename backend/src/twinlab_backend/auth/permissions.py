"""Permission and role definitions (RBAC v2 — scoped).

Permissions are code-defined constants, tagged **lab-scoped** or **global-only**.
Roles are code-defined bundles of permissions, each tagged with the scope(s) it may
be bound at (global and/or a specific lab). Authorization resolves a role's
permissions from this catalog — the DB `roles`/`permissions` tables are seeded from
here for introspection, but the catalog is the source of truth.

A **binding** ties a principal (user or group) to a role at a scope (global, or one
lab). Effective permissions on a lab = the union over the principal's bindings, with
lab bindings masked to the lab-scoped set, plus the owner's implicit `lab_owner` set.
See `auth.service` for the resolver and `docs/rbac-v2.md` for the model.
"""

from dataclasses import dataclass
from typing import Final

# --- Permission names, as stored in the `permissions` table. ---

# Lab-scoped: meaningful on a specific lab, and bindable per-lab or globally (a
# global binding of one of these = "on every lab, including future ones").
LAB_READ: Final = "lab:read"
LAB_EDIT: Final = "lab:edit"  # edit definition, redeploy, author suites/custom-config
LAB_CONFIGURE: Final = "lab:configure"
LAB_VALIDATE: Final = "lab:validate"
LAB_TERMINAL: Final = "lab:terminal"
LAB_DESTROY: Final = "lab:destroy"
LAB_GRANT: Final = "lab:grant"  # manage bindings on this lab (delegate roles)

# Global-only: a lab scope is meaningless for these.
LAB_CREATE: Final = "lab:create"  # create a brand-new lab (creator becomes owner)
USER_MANAGE: Final = "user:manage"
GROUP_MANAGE: Final = "group:manage"
# Author the template library's user tier (delta 21): the lab publish toggle +
# node-template CRUD. Library READS need no permission — any authenticated user.
TEMPLATE_MANAGE: Final = "template:manage"

LAB_SCOPED_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {LAB_READ, LAB_EDIT, LAB_CONFIGURE, LAB_VALIDATE, LAB_TERMINAL, LAB_DESTROY, LAB_GRANT}
)
GLOBAL_ONLY_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {LAB_CREATE, USER_MANAGE, GROUP_MANAGE, TEMPLATE_MANAGE}
)
ALL_PERMISSIONS: Final[tuple[str, ...]] = tuple(
    sorted(LAB_SCOPED_PERMISSIONS | GLOBAL_ONLY_PERMISSIONS)
)

# --- Scope + principal kinds (stored on a binding row). ---
SCOPE_GLOBAL: Final = "global"
SCOPE_LAB: Final = "lab"
PRINCIPAL_USER: Final = "user"
PRINCIPAL_GROUP: Final = "group"

ADMIN_ROLE: Final = "admin"
# The baseline role every new user gets: authenticated, but no inherent access.
DEFAULT_USER_ROLE: Final = "user"


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """A code-defined role: the permissions it grants and the scope(s) at which a
    binding may attach it."""

    permissions: frozenset[str]
    scopes: frozenset[str]  # subset of {SCOPE_GLOBAL, SCOPE_LAB}


# Lab-role permission bundles (all drawn from LAB_SCOPED_PERMISSIONS).
_LAB_OWNER: Final = LAB_SCOPED_PERMISSIONS  # everything on the lab, incl. grant + destroy
_LAB_MANAGER: Final = frozenset(
    {LAB_READ, LAB_EDIT, LAB_CONFIGURE, LAB_VALIDATE, LAB_TERMINAL, LAB_GRANT}
)  # read-write + delegate, but not destroy
_LAB_OPERATOR: Final = frozenset({LAB_READ, LAB_CONFIGURE, LAB_VALIDATE, LAB_TERMINAL})
_LAB_VIEWER: Final = frozenset({LAB_READ})

# The role catalog. Global-bindable roles may grant global-only permissions; lab-
# bindable roles carry only lab-scoped permissions.
ROLE_CATALOG: Final[dict[str, RoleSpec]] = {
    # Global-bindable
    ADMIN_ROLE: RoleSpec(frozenset(ALL_PERMISSIONS), frozenset({SCOPE_GLOBAL})),
    # template:manage: operators author labs, so curating the library's starting
    # points fits the role (delta 21, approved 2026-08-04).
    "global_operator": RoleSpec(
        frozenset({LAB_CREATE, TEMPLATE_MANAGE}) | LAB_SCOPED_PERMISSIONS,
        frozenset({SCOPE_GLOBAL}),
    ),
    "global_viewer": RoleSpec(frozenset({LAB_READ}), frozenset({SCOPE_GLOBAL})),
    "creator": RoleSpec(frozenset({LAB_CREATE}), frozenset({SCOPE_GLOBAL})),
    DEFAULT_USER_ROLE: RoleSpec(frozenset(), frozenset({SCOPE_GLOBAL})),
    # Lab-bindable
    "lab_owner": RoleSpec(_LAB_OWNER, frozenset({SCOPE_LAB})),
    "lab_manager": RoleSpec(_LAB_MANAGER, frozenset({SCOPE_LAB})),
    "lab_operator": RoleSpec(_LAB_OPERATOR, frozenset({SCOPE_LAB})),
    "lab_viewer": RoleSpec(_LAB_VIEWER, frozenset({SCOPE_LAB})),
}

# The owner's implicit permission set on their own lab (no binding row needed).
LAB_OWNER_PERMISSIONS: Final[frozenset[str]] = _LAB_OWNER

# Role name -> granted permissions, for seeding the DB introspection tables.
ROLE_DEFINITIONS: Final[dict[str, tuple[str, ...]]] = {
    name: tuple(sorted(spec.permissions)) for name, spec in ROLE_CATALOG.items()
}


def role_permissions(role_name: str) -> frozenset[str]:
    """Permissions a role grants. An unknown role (e.g. a stale name from before a
    catalog change) grants nothing rather than raising — a binding to a role that no
    longer exists is inert, not an error."""
    spec = ROLE_CATALOG.get(role_name)
    return spec.permissions if spec is not None else frozenset()


def role_bindable_at(role_name: str, scope_type: str) -> bool:
    """Whether `role_name` may be bound at `scope_type`. Unknown role -> False."""
    spec = ROLE_CATALOG.get(role_name)
    return spec is not None and scope_type in spec.scopes


def global_bindable_roles() -> tuple[str, ...]:
    return tuple(n for n, s in ROLE_CATALOG.items() if SCOPE_GLOBAL in s.scopes)


def lab_bindable_roles() -> tuple[str, ...]:
    return tuple(n for n, s in ROLE_CATALOG.items() if SCOPE_LAB in s.scopes)
