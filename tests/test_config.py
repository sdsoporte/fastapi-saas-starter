"""Tests for app.config — Settings() fail-fast on missing SECRET_KEY in non-DEBUG."""
from __future__ import annotations

import pytest

from app.config import Settings


class TestSettingsSecretKeyFailFast:
    """Settings must raise when SECRET_KEY is empty AND DEBUG is False (production mode)."""

    def test_raises_runtime_error_when_secret_key_empty_and_debug_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: non-DEBUG environment with empty SECRET_KEY
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Act + Assert
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            Settings()

    def test_raises_when_secret_key_missing_and_debug_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: SECRET_KEY not provided, DEBUG off
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Act + Assert
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            Settings()

    def test_allows_empty_secret_key_when_debug_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: DEBUG on → empty SECRET_KEY is acceptable (dev convenience)
        monkeypatch.setenv("SECRET_KEY", "")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Act
        settings = Settings()

        # Assert: build succeeds; placeholder is filled in for dev
        assert settings.SECRET_KEY, "DEBUG mode must auto-generate a non-empty SECRET_KEY"
        assert settings.DEBUG is True

    def test_loads_configured_values_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: valid SECRET_KEY + explicit values
        monkeypatch.setenv("SECRET_KEY", "this-is-a-test-secret-key-32+chars-1234")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
        monkeypatch.setenv("REDIS_URL", "redis://redis:6379/1")
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "45")
        monkeypatch.setenv("API_V1_PREFIX", "/api/v2")

        # Act
        settings = Settings()

        # Assert: all values reflect the environment
        assert settings.SECRET_KEY == "this-is-a-test-secret-key-32+chars-1234"
        assert settings.DEBUG is False
        assert settings.DATABASE_URL == "postgresql+asyncpg://u:p@db:5432/x"
        assert settings.REDIS_URL == "redis://redis:6379/1"
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 45
        assert settings.API_V1_PREFIX == "/api/v2"


def test_settings_module_is_importable() -> None:
    """Sanity import test — guards against misconfigured package exports."""
    from app import config  # noqa: F401

    assert hasattr(config, "Settings")
