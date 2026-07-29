"""Registered SSH public keys, backed by the `ssh_keys` table.

Mirrors `api_keys`, with one twist: nothing secret is stored or shown —
create returns the row itself. Fingerprints are globally unique (sshd's jump
lookup carries only the fingerprint, so a key identifies exactly one person);
names are per-user labels.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth.ssh_pubkey import parse_public_key
from twinlab_backend.db.models import SshKey
from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class SshKeyStoreError:
    # "invalid_public_key" | "unsupported_key_type" | "name_taken"
    # | "key_already_registered" | "not_found"
    reason: str
    detail: str = ""


async def create_key(
    session: AsyncSession, user_id: uuid.UUID, name: str, public_key: str
) -> Result[SshKey, SshKeyStoreError]:
    parsed = parse_public_key(public_key)
    if isinstance(parsed, Err):
        return Err(SshKeyStoreError(parsed.error.reason, parsed.error.detail))
    key = parsed.value
    name_taken = await session.scalar(
        select(SshKey).where(SshKey.user_id == user_id, SshKey.name == name)
    )
    if name_taken is not None:
        return Err(SshKeyStoreError("name_taken", name))
    registered = await session.scalar(select(SshKey).where(SshKey.fingerprint == key.fingerprint))
    if registered is not None:
        return Err(SshKeyStoreError("key_already_registered", key.fingerprint))
    row = SshKey(
        user_id=user_id,
        name=name,
        algorithm=key.algorithm,
        key_b64=key.key_b64,
        comment=key.comment,
        fingerprint=key.fingerprint,
    )
    session.add(row)
    await session.commit()
    return Ok(row)


async def list_keys(session: AsyncSession, user_id: uuid.UUID) -> list[SshKey]:
    rows = await session.scalars(
        select(SshKey).where(SshKey.user_id == user_id).order_by(SshKey.created_at)
    )
    return list(rows.all())


async def delete_key(
    session: AsyncSession, user_id: uuid.UUID, key_id: uuid.UUID
) -> SshKeyStoreError | None:
    """Delete one of the caller's own keys; someone else's key is a plain
    not-found (existence hidden)."""
    row = await session.scalar(select(SshKey).where(SshKey.id == key_id, SshKey.user_id == user_id))
    if row is None:
        return SshKeyStoreError("not_found")
    await session.delete(row)
    await session.commit()
    return None


async def resolve_fingerprint(session: AsyncSession, fingerprint: str) -> SshKey | None:
    """Look up a key by sshd's %f token ("SHA256:<base64>"; a bare hash is
    tolerated). None covers unknown keys AND inactive owners — at the jump
    both mean the same thing: no authorized_keys line. Stamps last_used_at
    (the key was offered; agents offer every key they hold, so unknown
    fingerprints here are routine, not suspicious)."""
    value = fingerprint if fingerprint.startswith("SHA256:") else f"SHA256:{fingerprint}"
    row = await session.scalar(select(SshKey).where(SshKey.fingerprint == value))
    if row is None or not row.user.is_active:
        return None
    row.last_used_at = datetime.now(UTC)
    await session.commit()
    return row
