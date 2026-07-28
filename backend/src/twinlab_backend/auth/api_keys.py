"""API keys: long-lived Bearer credentials, backed by the `api_keys` table.

A key acts as its creating user with that user's permissions (no separate key
scoping in v1). The raw secret ("tl_<random>") is returned once at creation
and stored only as its sha256 — deterministic, so the Bearer lookup is by
hash (safe for a high-entropy random secret, unlike a password).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import ApiKey, User
from twinlab_backend.result import Err, Ok, Result

_KEY_PREFIX = "tl_"
_KEY_BYTES = 32


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApiKeyError:
    reason: str  # "name_taken" | "not_found" | "invalid"
    detail: str = ""


async def create_key(
    session: AsyncSession, user_id: uuid.UUID, name: str
) -> Result[tuple[str, ApiKey], ApiKeyError]:
    """Create a key and return `(raw_secret, row)` — the only time the secret
    exists in the clear."""
    taken = await session.scalar(
        select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.name == name)
    )
    if taken is not None:
        return Err(ApiKeyError("name_taken", name))
    raw_key = _KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
    row = ApiKey(user_id=user_id, name=name, token_hash=_hash_key(raw_key))
    session.add(row)
    await session.commit()
    return Ok((raw_key, row))


async def list_keys(session: AsyncSession, user_id: uuid.UUID) -> list[ApiKey]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at)
    )
    return list(rows.all())


async def revoke_key(
    session: AsyncSession, user_id: uuid.UUID, key_id: uuid.UUID
) -> ApiKeyError | None:
    """Delete one of the caller's own keys; someone else's key is a plain
    not-found (existence hidden)."""
    row = await session.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
    if row is None:
        return ApiKeyError("not_found")
    await session.delete(row)
    await session.commit()
    return None


async def resolve_key(session: AsyncSession, raw_key: str) -> Result[User, ApiKeyError]:
    """Authenticate a Bearer secret: the key must exist and its user be active.
    Stamps `last_used_at`."""
    row = await session.scalar(select(ApiKey).where(ApiKey.token_hash == _hash_key(raw_key)))
    if row is None or not row.user.is_active:
        return Err(ApiKeyError("invalid"))
    row.last_used_at = datetime.now(UTC)
    await session.commit()
    return Ok(row.user)
