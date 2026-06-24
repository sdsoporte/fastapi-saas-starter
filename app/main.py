"""FastAPI application factory.

`create_app()` is the canonical entry point — it wires routers, middleware,
CORS, and a lifespan context. Keeping it as a factory (instead of a module
level `app = ...`) makes the test suite trivially fresh per test.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks. Foundation slice: no-op beyond logging."""
    get_settings()  # validated up-front; raises if SECRET_KEY is missing in non-DEBUG
    # Startup
    yield
    # Shutdown (no resources to release in the foundation slice)


def create_app() -> FastAPI:
    """Build and return a configured FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Liveness probe (no DB, no Redis) ---
    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- API v1 router stub ---
    # Routers are added in later PRs (auth, health/detailed, tenants, users, plans).
    @app.get(f"{settings.API_V1_PREFIX}/", tags=["meta"])
    async def api_v1_root() -> dict[str, str]:
        return {"message": f"{settings.APP_NAME} API v1"}

    return app
