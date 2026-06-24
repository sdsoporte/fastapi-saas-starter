"""Health router: GET /health/detailed — deep readiness probe.

The detailed probe checks PostgreSQL (`SELECT 1`) and Redis (`PING`),
each wrapped in a 2-second timeout. Failures return a structured error
chunk instead of raising, so the endpoint itself never crashes.

`/health` (liveness) is registered directly on the app in `app/main.py`
because it MUST stay independent of every dependency.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import redis.asyncio as redis_asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine

router = APIRouter(tags=["health"])

PROBE_TIMEOUT_SECONDS = 2.0


async def _postgres_probe() -> dict[str, Any]:
    """Run `SELECT 1` against the configured engine with a 2s budget."""
    start = time.perf_counter()
    try:
        engine = get_engine()

        async def _do() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_do(), timeout=PROBE_TIMEOUT_SECONDS)
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    except TimeoutError:
        return {
            "status": "error",
            "latency_ms": round(PROBE_TIMEOUT_SECONDS * 1000, 2),
            "message": "timeout",
        }
    except Exception as exc:  # connection refused, DNS, etc.
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "message": str(exc) or exc.__class__.__name__,
        }


async def _redis_probe() -> dict[str, Any]:
    """Issue `PING` against the configured Redis with a 2s budget."""
    start = time.perf_counter()
    client: redis_asyncio.Redis | None = None
    try:
        settings = get_settings()
        client = redis_asyncio.from_url(
            settings.REDIS_URL, decode_responses=True
        )

        async def _do() -> None:
            await client.ping()

        await asyncio.wait_for(_do(), timeout=PROBE_TIMEOUT_SECONDS)
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    except TimeoutError:
        return {
            "status": "error",
            "latency_ms": round(PROBE_TIMEOUT_SECONDS * 1000, 2),
            "message": "timeout",
        }
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "message": str(exc) or exc.__class__.__name__,
        }
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


@router.get("/health/detailed", include_in_schema=False)
async def detailed_health() -> JSONResponse:
    """Aggregate Postgres + Redis probes into a single readiness response."""
    postgres = await _postgres_probe()
    redis_status = await _redis_probe()
    overall_ok = postgres["status"] == "ok" and redis_status["status"] == "ok"
    return JSONResponse(
        status_code=200 if overall_ok else 503,
        content={
            "status": "ok" if overall_ok else "error",
            "checks": {"postgres": postgres, "redis": redis_status},
        },
    )