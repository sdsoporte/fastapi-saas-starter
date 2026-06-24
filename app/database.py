"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

`Base` is imported by every model module and by Alembic's env.py.
`get_db` is the canonical FastAPI dependency; it yields a session,
commits on clean exit, rolls back on exception, and always closes.

Engine and session factory are created lazily so importing this module
does not require a fully populated environment (useful for tests and
Alembic env.py which set their own DATABASE_URL).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Return a memoized AsyncEngine; optionally built from an explicit URL.

    The first call uses the configured DATABASE_URL (or the override).
    Subsequent calls reuse the memoized engine.
    """
    global _engine
    if _engine is None:
        from app.config import get_settings

        url = database_url or get_settings().DATABASE_URL
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the memoized session factory, building the engine if needed."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Drop the memoized engine and session factory (used by tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def AsyncSessionLocal() -> AsyncSession:  # type: ignore[no-redef]
    """Compatibility shim: callable returning a new AsyncSession."""
    return get_session_factory()()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, commit/rollback, close.

    - Clean exit (consumer returns)        -> commit + close
    - Consumer raises (any exception)      -> rollback + close + re-raise
    - Generator is closed (request done)   -> ensure close
    """
    session: AsyncSession = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
