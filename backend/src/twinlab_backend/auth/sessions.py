"""Opaque login sessions, backed by the `sessions` table.

The raw token is a random URL-safe string handed to the client (in an httpOnly
cookie); only its sha256 is stored, so a database leak does not expose usable
tokens. Sessions are revocable (logout) and expire.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.db.models import Session, User
from twinlab_backend.result import Err, Ok, Result

_TOKEN_BYTES = 32


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SessionError:
    reason: str  # "invalid" or "expired"


async def create_session(session: AsyncSession, user_id: uuid.UUID, ttl: timedelta) -> str:
    """Create a session and return the raw token (stored only as its hash)."""
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    session.add(
        Session(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.commit()
    return raw_token


async def resolve_session(session: AsyncSession, raw_token: str) -> Result[User, SessionError]:
    row = await session.scalar(select(Session).where(Session.token_hash == _hash_token(raw_token)))
    if row is None or row.revoked_at is not None or not row.user.is_active:
        return Err(SessionError("invalid"))
    if row.expires_at <= datetime.now(UTC):
        return Err(SessionError("expired"))
    return Ok(row.user)


async def revoke_session(session: AsyncSession, raw_token: str) -> None:
    row = await session.scalar(select(Session).where(Session.token_hash == _hash_token(raw_token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.commit()


async def revoke_all_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, keep_raw_token: str | None = None
) -> None:
    """Revoke every live session of a user — password reset, deactivation,
    deletion. `keep_raw_token` spares one session: a self-service password
    change keeps the session that made it."""
    keep_hash = _hash_token(keep_raw_token) if keep_raw_token is not None else None
    rows = await session.scalars(
        select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    )
    now = datetime.now(UTC)
    for row in rows.all():
        if keep_hash is not None and row.token_hash == keep_hash:
            continue
        row.revoked_at = now
    await session.commit()
