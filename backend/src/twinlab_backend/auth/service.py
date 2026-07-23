"""Authentication service: verify credentials, compute effective permissions."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth.passwords import hash_password, verify_password
from twinlab_backend.db.models import User
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


def effective_permissions(user: User) -> set[str]:
    """Union of the permissions granted by all of the user's roles."""
    return {perm.name for role in user.roles for perm in role.permissions}
