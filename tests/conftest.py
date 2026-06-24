"""Pytest configuration and shared fixtures for the fastapi-saas-starter test suite.

Imports of production modules are deferred to fixture call time so that
partial implementations (e.g. config-only slices) can still load this
conftest and run their tests.
"""
from __future__ import annotations

import os

# --- Environment defaults for the test session ---
# Set BEFORE any app module imports Settings(). `setdefault` so per-test
# monkeypatch overrides still win; tests that exercise the fail-fast path
# explicitly set DEBUG=false + empty SECRET_KEY.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-padding-1234567890abcdef")
# Use SQLite-in-memory for the default engine so unit-level tests that call
# get_db() / get_session_factory() directly do not require a live Postgres.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    """Drop the memoized Settings / engine between tests.

    Each test must see a fresh Settings built from the (possibly monkeypatched)
    environment, and a fresh engine bound to whatever DATABASE_URL is current.
    """
    from app.config import reset_settings_cache
    from app.database import reset_engine

    reset_settings_cache()
    reset_engine()
    yield
    reset_settings_cache()
    reset_engine()


@pytest_asyncio.fixture
async def async_engine() -> AsyncIterator[Any]:
    """Yield an in-memory aiosqlite engine with schema created; drop on teardown."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine: Any) -> AsyncIterator[Any]:
    """Yield an AsyncSession bound to the in-memory engine for direct DAO tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, autoflush=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[Any]:
    """Yield an httpx AsyncClient wired to a fresh in-process FastAPI app."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
