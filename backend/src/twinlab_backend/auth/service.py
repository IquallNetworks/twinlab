"""Authentication + the scoped-authorization resolver.

`authenticate` verifies credentials. The rest computes a principal's **effective
permissions**, either globally or on a specific lab, from their role bindings:

- Own bindings + every binding on a group the user belongs to.
- A **global** binding contributes its role's full permission set.
- A **lab** binding contributes (role permissions ∩ lab-scoped) only on that lab.
- The lab's **owner** implicitly holds the full `lab_owner` set on that lab.

The core (`resolve_permissions`) is a pure function over a list of `Grant`s, so it is
unit-testable without a database; the async wrappers load the grants and call it.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password, verify_password
from twinlab_backend.db.models import Lab, RoleBinding, User
from twinlab_backend.result import Err, Ok, Result

# A throwaway hash so authentication does the same argon2 work whether or not the
# user exists — avoids leaking account existence through response timing.
_DUMMY_HASH = hash_password("twinlab-timing-equalizer")


@dataclass(frozen=True, slots=True)
class AuthError:
    # "invalid_credentials" (unknown user or wrong password) or "inactive".
    reason: str


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> Result[User, AuthError]:
    user = await session.scalar(select(User).where(User.username == username))
    candidate_hash = user.password_hash if user is not None else _DUMMY_HASH
    if not verify_password(password, candidate_hash) or user is None:
        return Err(AuthError("invalid_credentials"))
    if not user.is_active:
        return Err(AuthError("inactive"))
    return Ok(user)


@dataclass(frozen=True, slots=True)
class Grant:
    """A binding reduced to what the resolver needs: which role, at what scope, on
    which lab (None for a global grant)."""

    role_name: str
    scope_type: str
    lab_id: uuid.UUID | None


def resolve_permissions(
    grants: Iterable[Grant], lab_id: uuid.UUID | None, *, is_owner: bool
) -> set[str]:
    """Effective permissions from a principal's grants, evaluated for one lab (or
    globally when `lab_id` is None). Global grants always contribute; a lab grant
    contributes its lab-scoped permissions only when it names `lab_id`. The owner's
    implicit set is added when `is_owner` and a lab is in view."""
    result: set[str] = set()
    for grant in grants:
        if grant.scope_type == perms.SCOPE_GLOBAL:
            result |= perms.role_permissions(grant.role_name)
        elif grant.scope_type == perms.SCOPE_LAB and lab_id is not None and grant.lab_id == lab_id:
            result |= perms.role_permissions(grant.role_name) & perms.LAB_SCOPED_PERMISSIONS
    if is_owner and lab_id is not None:
        result |= perms.LAB_OWNER_PERMISSIONS
    return result


async def load_grants(session: AsyncSession, user: User) -> list[Grant]:
    """All bindings that apply to a user: their own, plus every group they're in."""
    group_ids = [group.id for group in user.groups]
    principal_match = (RoleBinding.principal_type == perms.PRINCIPAL_USER) & (
        RoleBinding.principal_id == user.id
    )
    if group_ids:
        principal_match = or_(
            principal_match,
            (RoleBinding.principal_type == perms.PRINCIPAL_GROUP)
            & (RoleBinding.principal_id.in_(group_ids)),
        )
    rows = await session.scalars(select(RoleBinding).where(principal_match))
    return [Grant(r.role_name, r.scope_type, r.lab_id) for r in rows.all()]


async def effective_permissions_for(session: AsyncSession, user: User, lab: Lab) -> set[str]:
    """A user's effective permissions on one lab."""
    grants = await load_grants(session, user)
    return resolve_permissions(grants, lab.id, is_owner=lab.owner_id == user.id)


async def effective_permissions_bulk(
    session: AsyncSession, user: User, labs: list[Lab]
) -> dict[uuid.UUID, set[str]]:
    """A user's effective permissions on each of `labs`, loading their grants once —
    for listing, where per-lab permissions are needed for every row at no extra query
    cost per lab."""
    grants = await load_grants(session, user)
    return {
        lab.id: resolve_permissions(grants, lab.id, is_owner=lab.owner_id == user.id)
        for lab in labs
    }


async def global_permissions(session: AsyncSession, user: User) -> set[str]:
    """A user's global permissions (from global bindings only) — the set consulted
    for global-only checks like user:manage and lab:create."""
    grants = await load_grants(session, user)
    return resolve_permissions(grants, None, is_owner=False)


async def global_role_names(session: AsyncSession, user: User) -> list[str]:
    """The names of a user's own global role bindings (for display in /auth/me and
    the users list). Group- and lab-scoped grants are not included here."""
    rows = await session.scalars(
        select(RoleBinding.role_name).where(
            RoleBinding.principal_type == perms.PRINCIPAL_USER,
            RoleBinding.principal_id == user.id,
            RoleBinding.scope_type == perms.SCOPE_GLOBAL,
        )
    )
    return sorted(set(rows.all()))


async def permitted_lab_ids(
    session: AsyncSession, user: User, permission: str
) -> set[uuid.UUID] | None:
    """The set of lab ids on which the user holds a LAB-SCOPED `permission`,
    or None meaning "all" (a global grant carries it). Owned labs are always
    included — an owner implicitly holds every lab-scoped permission. Used to
    filter listings, the events stream, and the SSH jump's authorized-keys
    answer without checking labs one at a time."""
    grants = await load_grants(session, user)
    if permission in resolve_permissions(grants, None, is_owner=False):
        return None
    permitted = {
        grant.lab_id
        for grant in grants
        if grant.scope_type == perms.SCOPE_LAB
        and grant.lab_id is not None
        and permission in perms.role_permissions(grant.role_name)
    }
    owned = await session.scalars(select(Lab.id).where(Lab.owner_id == user.id))
    permitted |= set(owned.all())
    return permitted


async def permitted_lab_names(
    session: AsyncSession, user: User, permission: str
) -> set[str] | None:
    """The lab *names* variant of `permitted_lab_ids` — the events stream and
    the clab-api inventory are keyed by name, so they filter on this."""
    ids = await permitted_lab_ids(session, user, permission)
    if ids is None:
        return None
    if not ids:
        return set()
    rows = await session.scalars(select(Lab.name).where(Lab.id.in_(ids)))
    return set(rows.all())
