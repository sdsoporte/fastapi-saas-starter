"""Tests for authentication: POST /api/v1/auth/login + get_current_user.

RED-first: tests reference production modules that do not yet exist
(`app.routers.auth`, `app.schemas.auth`, `app.core.dependencies`).
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

# --- Fixture factory ---------------------------------------------------------


async def _build_auth_client(
    *,
    tenant_status: Any = None,
    user_is_active: bool = True,
    user_role: Any = None,
    user_email: str = "admin@acme.com",
    password: str = "S3cret-pass",
) -> AsyncIterator[tuple[AsyncClient, dict[str, Any]]]:
    """Yield (AsyncClient, snapshot) sharing one in-memory aiosqlite engine.

    `get_db` is overridden so the app and the seed session hit the same DB.
    The snapshot exposes tenant_id, user_id, password, and email so tests
    can decode tokens or assert response shapes without re-querying.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.security import hash_password
    from app.database import Base, get_db
    from app.main import create_app
    from app.models.tenant import Tenant, TenantStatus
    from app.models.user import User, UserRole

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )

    app = create_app()

    async def _override_get_db() -> AsyncIterator[Any]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)

    tenant_status = tenant_status or TenantStatus.ACTIVE
    user_role = user_role or UserRole.TENANT_ADMIN

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with factory() as seed:
            tenant = Tenant(name="Acme", slug="acme", status=tenant_status)
            seed.add(tenant)
            await seed.flush()
            user = User(
                tenant_id=tenant.id,
                email=user_email,
                full_name="Admin",
                hashed_password=hash_password(password),
                role=user_role,
                is_active=user_is_active,
            )
            seed.add(user)
            await seed.commit()
            snap: dict[str, Any] = {
                "tenant_id": str(tenant.id),
                "user_id": str(user.id),
                "password": password,
                "email": user_email,
            }

        try:
            yield ac, snap
        finally:
            app.dependency_overrides.clear()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()


@pytest_asyncio.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, dict[str, Any]]]:
    """Default happy-path fixture: ACTIVE tenant + ACTIVE tenant_admin."""
    async for item in _build_auth_client():
        yield item


@pytest_asyncio.fixture
async def auth_client_with_suspended_user() -> AsyncIterator[
    tuple[AsyncClient, dict[str, Any]]
]:
    """ACTIVE tenant with a user that has is_active=False."""
    async for item in _build_auth_client(user_is_active=False):
        yield item


@pytest_asyncio.fixture
async def auth_client_with_suspended_tenant() -> AsyncIterator[
    tuple[AsyncClient, dict[str, Any]]
]:
    """SUSPENDED tenant with an ACTIVE user inside."""
    from app.models.tenant import TenantStatus

    async for item in _build_auth_client(tenant_status=TenantStatus.SUSPENDED):
        yield item


async def _login(ac: AsyncClient, email: str, password: str) -> Any:
    return await ac.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )


# --- Login endpoint -----------------------------------------------------------


class TestLoginSuccess:
    """POST /api/v1/auth/login returns 200 + JWT + token_type + expires_in."""

    @pytest.mark.asyncio
    async def test_login_returns_200_and_bearer_token(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await _login(ac, snap["email"], snap["password"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str) and body["access_token"]
        assert body["expires_in"] == 1800

    @pytest.mark.asyncio
    async def test_login_token_carries_required_claims(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await _login(ac, snap["email"], snap["password"])
        assert resp.status_code == 200
        # Decode without verification to inspect raw claims.
        payload = jwt.decode(
            resp.json()["access_token"], options={"verify_signature": False}
        )
        assert payload["sub"] == snap["user_id"]
        assert payload["tenant_id"] == snap["tenant_id"]
        assert payload["role"] == "tenant_admin"
        assert isinstance(payload["iat"], int)
        assert isinstance(payload["exp"], int)
        # exp is 30 minutes after iat.
        assert payload["exp"] - payload["iat"] == 1800


class TestLoginFailures:
    """Wrong credentials return 401, never leak which side was wrong."""

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await _login(ac, snap["email"], "wrong-pass")
        assert resp.status_code == 401
        assert resp.json()["detail"].lower() == "invalid credentials"

    @pytest.mark.asyncio
    async def test_unknown_email_returns_401(self, auth_client) -> None:
        ac, _ = auth_client
        resp = await _login(ac, "ghost@nowhere.com", "whatever")
        assert resp.status_code == 401
        assert resp.json()["detail"].lower() == "invalid credentials"

    @pytest.mark.asyncio
    async def test_missing_password_returns_422(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await ac.post(
            "/api/v1/auth/login",
            data={"username": snap["email"]},
        )
        assert resp.status_code == 422


class TestLoginTimingEqualisation:
    """Unknown email and wrong password take roughly the same time.

    Anti-enumeration: an attacker must not be able to distinguish between
    'no such user' and 'wrong password for real user' via response timing.
    Both paths must perform a bcrypt comparison so neither leaks.
    """

    @pytest.mark.asyncio
    async def test_unknown_email_timing_close_to_wrong_password(
        self, auth_client
    ) -> None:
        ac, snap = auth_client

        # Warm bcrypt (cold first call is much slower than subsequent ones).
        await _login(ac, snap["email"], "warm-up-call")

        # Wrong password for real user.
        t0 = time.perf_counter()
        r1 = await _login(ac, snap["email"], "wrong")
        wrong_ms = (time.perf_counter() - t0) * 1000
        assert r1.status_code == 401

        # Unknown email.
        t0 = time.perf_counter()
        r2 = await _login(ac, "ghost@nowhere.com", "whatever")
        unknown_ms = (time.perf_counter() - t0) * 1000
        assert r2.status_code == 401

        ratio = max(wrong_ms, unknown_ms) / min(wrong_ms, unknown_ms)
        assert ratio < 5.0, (
            f"timing leak: wrong={wrong_ms:.1f}ms unknown={unknown_ms:.1f}ms "
            f"ratio={ratio:.2f}"
        )


# --- get_current_user (via /api/v1/auth/me) ---------------------------------


class TestGetCurrentUserHappyPath:
    """A valid bearer token resolves to the user identified by `sub`."""

    @pytest.mark.asyncio
    async def test_me_returns_user_for_valid_token(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await _login(ac, snap["email"], snap["password"])
        token = resp.json()["access_token"]

        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200
        body = me.json()
        assert body["id"] == snap["user_id"]
        assert body["email"] == snap["email"]
        assert body["role"] == "tenant_admin"
        assert body["tenant_id"] == snap["tenant_id"]
        assert body["is_active"] is True
        # No password / hash field leaks.
        assert "password" not in body
        assert "hashed_password" not in body


class TestGetCurrentUserRejections:
    """get_current_user must reject bad/missing tokens with HTTP 401."""

    @pytest.mark.asyncio
    async def test_missing_authorization_header_returns_401(
        self, auth_client
    ) -> None:
        ac, _ = auth_client
        resp = await ac.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_tampered_signature_returns_401(self, auth_client) -> None:
        ac, snap = auth_client
        resp = await _login(ac, snap["email"], snap["password"])
        token = resp.json()["access_token"]
        # Flip a character in the middle of the signature (avoid base64
        # boundary padding issues that made an earlier version flaky).
        head, mid, sig = token.split(".")
        replacement = "B" if sig[5] != "B" else "C"
        tampered = f"{head}.{mid}.{sig[:5]}{replacement}{sig[6:]}"
        assert tampered != token

        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"}
        )
        assert me.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, auth_client) -> None:
        from app.core.security import create_access_token

        ac, snap = auth_client
        expired = create_access_token(
            subject=snap["user_id"],
            tenant_id=snap["tenant_id"],
            role="tenant_admin",
            expires_minutes=-1,
        )
        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
        )
        assert me.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_token_returns_401(self, auth_client) -> None:
        ac, _ = auth_client
        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert me.status_code == 401


# --- Suspended accounts -------------------------------------------------------


class TestSuspendedRejections:
    """Login may succeed, but /me must reject suspended accounts."""

    @pytest.mark.asyncio
    async def test_inactive_user_blocked_at_me(
        self, auth_client_with_suspended_user
    ) -> None:
        ac, snap = auth_client_with_suspended_user
        resp = await _login(ac, snap["email"], snap["password"])
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 401
        assert "suspended" in me.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_suspended_tenant_blocks_me(
        self, auth_client_with_suspended_tenant
    ) -> None:
        ac, snap = auth_client_with_suspended_tenant
        resp = await _login(ac, snap["email"], snap["password"])
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        me = await ac.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 401
        assert "suspended" in me.json()["detail"].lower()