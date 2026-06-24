"""Alembic environment — async engine wired to the app's Base.metadata.

Reads `DATABASE_URL` from the environment (so the same `alembic.ini` works
for local, CI, and Docker). Falls back to `alembic.ini`'s `sqlalchemy.url`
when no env var is set (useful for `alembic` CLI without exporting env).

All migrations are executed via `connection.run_sync(...)` because Alembic's
DDL helpers are sync-only; this is the canonical SQLAlchemy 2.0 async recipe.
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing app.database pulls in the Base + every model via app.models.
# Keep these imports here (not at module top) so a bare `alembic` invocation
# without DATABASE_URL still loads cleanly; the actual connection happens
# in run_async_migrations below.
from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401 — ensure all models register on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from env when present.
_settings_database_url = os.getenv("DATABASE_URL") or get_settings().DATABASE_URL
config.set_main_option("sqlalchemy.url", _settings_database_url)

target_metadata = Base.metadata


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Build an async engine and execute migrations under a sync context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode is not supported for this project — Alembic must "
        "connect via the async engine so DDL is consistent with the "
        "async SQLAlchemy 2.0 stack used by the application."
    )

run_migrations_online()
