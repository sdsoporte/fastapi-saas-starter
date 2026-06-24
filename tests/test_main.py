"""Tests for app.main — create_app() factory, /health, lifespan, CORS, router wiring."""
from __future__ import annotations

import pytest


class TestCreateApp:
    """create_app() must build a working FastAPI instance with required surface."""

    def test_returns_fastapi_instance(self) -> None:
        from fastapi import FastAPI

        from app.main import create_app

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_expected_metadata(self) -> None:
        from app.main import create_app

        app = create_app()
        assert app.title  # non-empty
        assert app.version


class TestHealthEndpoint:
    """GET /health must be liveness-only and return 200 quickly."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"


class TestApiV1Prefix:
    """API v1 routes are mounted under the configured prefix; unknown returns 404."""

    @pytest.mark.asyncio
    async def test_unknown_v1_route_returns_404(self, client) -> None:
        resp = await client.get("/api/v1/this-does-not-exist")
        assert resp.status_code == 404


class TestCORS:
    """CORS middleware must be present and configured."""

    def test_cors_middleware_registered(self) -> None:
        from app.main import create_app

        app = create_app()
        # FastAPI stores middleware as a tuple on user_middleware
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes
