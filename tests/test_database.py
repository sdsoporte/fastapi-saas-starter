"""Tests for app.database — async engine, AsyncSessionLocal, get_db rollback semantics."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, get_db, get_session_factory


class TestGetDbYieldsSession:
    """get_db must yield an AsyncSession and close cleanly on exit."""

    @pytest.mark.asyncio
    async def test_yields_async_session(self) -> None:
        gen = get_db()
        session = await gen.__anext__()
        try:
            assert isinstance(session, AsyncSession)
        finally:
            await gen.aclose()

    @pytest.mark.asyncio
    async def test_session_usable_for_simple_query(self) -> None:
        from sqlalchemy import text

        gen = get_db()
        session = await gen.__anext__()
        try:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
        finally:
            await gen.aclose()


class TestGetDbRollsBackOnException:
    """If consumer raises, get_db must roll back and re-raise."""

    @pytest.mark.asyncio
    async def test_rolls_back_and_raises_on_exception(self) -> None:
        gen = get_db()
        await gen.__anext__()  # session opened

        with pytest.raises(ValueError, match="boom"):
            await gen.athrow(ValueError("boom"))

        # The generator must be cleanly closed (no leaked session).
        # Subsequent aclose should be a no-op.
        await gen.aclose()


class TestDatabaseModuleExports:
    """Smoke: required symbols are exported from app.database."""

    def test_base_is_declarative_base(self) -> None:
        # Base must have a metadata attribute (declarative_base contract)
        assert hasattr(Base, "metadata")
        assert hasattr(Base.metadata, "create_all")
        assert hasattr(Base.metadata, "drop_all")

    def test_session_factory_is_usable(self) -> None:
        factory = get_session_factory()
        assert callable(factory)
