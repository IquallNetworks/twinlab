"""Async SQLAlchemy engine, session factory, and declarative base."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def async_dsn(database_url: str) -> str:
    """Ensure the DSN names the async driver. Our `DATABASE_URL` uses the bare
    `postgresql://` form shared with other tools; SQLAlchemy's async engine needs
    the `+asyncpg` driver spelled out."""
    prefix = "postgresql://"
    if database_url.startswith(prefix):
        return "postgresql+asyncpg://" + database_url[len(prefix) :]
    return database_url


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping avoids handing out a connection the server has already closed.
    return create_async_engine(async_dsn(database_url), pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: attributes stay usable after commit, which suits
    # request handlers that read a model's fields after the session commits.
    return async_sessionmaker(engine, expire_on_commit=False)
