"""Tests for health endpoints: GET /health (liveness) + GET /health/detailed.

RED-first: tests reference code that does not exist yet
(`app.routers.health`, /health/detailed route on the app).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# --- Helpers -----------------------------------------------------------------


async def _client_for_app(app: Any) -> AsyncIterator[AsyncClient]:
    """AsyncClient wired to an arbitrary FastAPI app under test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- Liveness ----------------------------------------------------------------


class TestLiveness:
    """GET /health is process-up only; MUST NOT touch external deps."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_is_fast_no_db(self, client) -> None:
        """Liveness must respond in well under 50ms; no DB call required."""
        await client.get("/health")  # warm any cold paths
        t0 = time.perf_counter()
        for _ in range(5):
            resp = await client.get("/health")
            assert resp.status_code == 200
        avg_ms = ((time.perf_counter() - t0) / 5) * 1000
        assert avg_ms < 50.0, f"liveness too slow: {avg_ms:.1f}ms"


# --- Detailed health probes --------------------------------------------------


@pytest_asyncio.fixture
async def health_client() -> AsyncIterator[AsyncClient]:
    """Yield a client wired to a fresh app (no DB or Redis required)."""
    from app.main import create_app

    async for ac in _client_for_app(create_app()):
        yield ac


class TestDetailedHealthShape:
    """GET /health/detailed returns the structured checks payload."""

    @pytest.mark.asyncio
    async def test_endpoint_is_registered(self, health_client) -> None:
        resp = await health_client.get("/health/detailed")
        assert resp.status_code in {200, 503}, (
            f"/health/detailed returned {resp.status_code}; route must exist"
        )

    @pytest.mark.asyncio
    async def test_response_shape_contains_postgres_and_redis(
        self, health_client
    ) -> None:
        resp = await health_client.get("/health/detailed")
        body = resp.json()
        assert body["status"] in {"ok", "error"}
        assert "checks" in body
        assert "postgres" in body["checks"]
        assert "redis" in body["checks"]

    @pytest.mark.asyncio
    async def test_each_check_has_status_and_latency_ms(
        self, health_client
    ) -> None:
        resp = await health_client.get("/health/detailed")
        body = resp.json()
        for name, check in body["checks"].items():
            assert "status" in check, f"{name} missing status"
            assert check["status"] in {"ok", "error"}, f"{name} bad status"
            assert "latency_ms" in check, f"{name} missing latency_ms"
            assert isinstance(check["latency_ms"], (int, float))
            assert check["latency_ms"] >= 0


# --- Probe failure simulation ------------------------------------------------


def _fake_redis_probe(*, timeout: float = 0.05) -> Any:
    """Return a redis_probe coroutine that respects `timeout`."""

    async def _probe() -> dict[str, Any]:
        async def _ping() -> None:
            await asyncio.sleep(timeout * 10)  # exceeds the timeout

        try:
            await asyncio.wait_for(_ping(), timeout=timeout)
        except TimeoutError:
            return {
                "status": "error",
                "latency_ms": round(timeout * 1000, 2),
                "message": "timeout",
            }
        return {"status": "ok", "latency_ms": round(timeout * 1000, 2)}

    return _probe


class TestProbeFailures:
    """Probe failures must NOT raise — they must return a structured error."""

    @pytest.mark.asyncio
    async def test_postgres_down_returns_503_with_error_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.main import create_app

        async def _pg_down() -> dict[str, Any]:
            return {
                "status": "error",
                "latency_ms": 1.0,
                "message": "connection refused",
            }

        monkeypatch.setattr("app.routers.health._postgres_probe", _pg_down)
        monkeypatch.setattr(
            "app.routers.health._redis_probe",
            _fake_redis_probe(timeout=0.01),
        )

        async for ac in _client_for_app(create_app()):
            resp = await ac.get("/health/detailed")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "error"
        assert body["checks"]["postgres"]["status"] == "error"
        assert "message" in body["checks"]["postgres"]

    @pytest.mark.asyncio
    async def test_redis_down_returns_503_with_error_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.main import create_app

        async def _pg_ok() -> dict[str, Any]:
            return {"status": "ok", "latency_ms": 0.5}

        async def _redis_down() -> dict[str, Any]:
            return {
                "status": "error",
                "latency_ms": 1.0,
                "message": "timeout",
            }

        monkeypatch.setattr("app.routers.health._postgres_probe", _pg_ok)
        monkeypatch.setattr("app.routers.health._redis_probe", _redis_down)

        async for ac in _client_for_app(create_app()):
            resp = await ac.get("/health/detailed")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "error"
        assert body["checks"]["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_probe_timeout_returns_error_no_uncaught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slow dependency must time out within ~2s and return error shape."""
        from app.main import create_app

        async def _slow() -> dict[str, Any]:
            await asyncio.sleep(5.0)  # well past the 2s budget
            return {"status": "ok", "latency_ms": 5000.0}  # unreachable

        async def _bounded() -> dict[str, Any]:
            try:
                return await asyncio.wait_for(_slow(), timeout=2.0)
            except TimeoutError:
                return {
                    "status": "error",
                    "latency_ms": 2000.0,
                    "message": "timeout",
                }

        monkeypatch.setattr("app.routers.health._postgres_probe", _bounded)
        monkeypatch.setattr(
            "app.routers.health._redis_probe",
            _fake_redis_probe(timeout=0.01),
        )

        async for ac in _client_for_app(create_app()):
            t0 = time.perf_counter()
            resp = await ac.get("/health/detailed")
            elapsed = time.perf_counter() - t0
        # Endpoint must respond within ~2.5s even when probe sleeps 5s.
        assert elapsed < 2.5, f"endpoint took {elapsed:.2f}s"
        assert resp.status_code == 503
        assert resp.json()["checks"]["postgres"]["status"] == "error"
        assert resp.json()["checks"]["postgres"]["message"] == "timeout"