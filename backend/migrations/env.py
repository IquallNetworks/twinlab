"""Alembic migration environment (async, via asyncpg)."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from twinlab_backend.db import models
from twinlab_backend.db.base import async_dsn

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing `models` registers every table on the metadata used for autogenerate.
target_metadata = models.Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required to run migrations")
    return async_dsn(url)


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = async_engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async())
