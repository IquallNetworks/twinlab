"""Database reachability probe.

The schema now exists, but readiness only needs to know the connection works —
a trivial `SELECT 1`. SQLAlchemy is the boundary here, so its exceptions are
translated into a typed result.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class DbError:
    message: str


async def ping(session: AsyncSession) -> Result[None, DbError]:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return Err(DbError(f"database query failed: {exc}"))
    return Ok(None)
