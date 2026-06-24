"""Auth login tests."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, dict[str, Any]]]:
    from app.core.security import hash_password
    from app.database import Base, get_db
    from app.main import create_app
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    app = create_app()

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with factory() as seed:
        tenant = Tenant(name="Acme", slug="acme")
        seed.add(tenant)
        await seed.flush()
        user = User(tenant_id=tenant.id, email="admin@acme.com", full_name="Admin", hashed_password=hash_password("S3cret-pass"), role=UserRole.TENANT_ADMIN)
        seed.add(user)
        await seed.commit()
        snap = {"tenant_id": str(tenant.id), "user_id": str(user.id), "email": user.email, "password": "S3cret-pass"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, snap
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _login(ac: AsyncClient, email: str, password: str):
    return await ac.post("/api/v1/auth/login", data={"username": email, "password": password})


@pytest.mark.asyncio
async def test_login_returns_bearer_token(auth_client) -> None:
    ac, snap = auth_client
    resp = await _login(ac, snap["email"], snap["password"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert body["access_token"]


@pytest.mark.asyncio
async def test_login_token_carries_required_claims(auth_client) -> None:
    ac, snap = auth_client
    resp = await _login(ac, snap["email"], snap["password"])
    payload = jwt.decode(resp.json()["access_token"], options={"verify_signature": False})
    assert payload["sub"] == snap["user_id"]
    assert payload["tenant_id"] == snap["tenant_id"]
    assert payload["role"] == "tenant_admin"
    assert payload["exp"] - payload["iat"] == 1800


@pytest.mark.asyncio
async def test_wrong_password_returns_401(auth_client) -> None:
    ac, snap = auth_client
    resp = await _login(ac, snap["email"], "wrong-pass")
    assert resp.status_code == 401
    assert resp.json()["detail"].lower() == "invalid credentials"


@pytest.mark.asyncio
async def test_unknown_email_returns_401(auth_client) -> None:
    ac, _ = auth_client
    resp = await _login(ac, "ghost@nowhere.com", "whatever")
    assert resp.status_code == 401
    assert resp.json()["detail"].lower() == "invalid credentials"


@pytest.mark.asyncio
async def test_missing_password_returns_422(auth_client) -> None:
    ac, snap = auth_client
    resp = await ac.post("/api/v1/auth/login", data={"username": snap["email"]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_returns_user_for_valid_token(auth_client) -> None:
    ac, snap = auth_client
    resp = await _login(ac, snap["email"], snap["password"])
    token = resp.json()["access_token"]
    me = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == snap["user_id"]
    assert body["email"] == snap["email"]
    assert body["tenant_id"] == snap["tenant_id"]
    assert body["role"] == "tenant_admin"
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(auth_client) -> None:
    ac, _ = auth_client
    resp = await ac.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tampered_signature_returns_401(auth_client) -> None:
    ac, snap = auth_client
    resp = await _login(ac, snap["email"], snap["password"])
    token = resp.json()["access_token"]
    head, mid, sig = token.split(".")
    replacement = "B" if sig[5] != "B" else "C"
    tampered = f"{head}.{mid}.{sig[:5]}{replacement}{sig[6:]}"
    assert tampered != token
    me = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(auth_client) -> None:
    from app.core.security import create_access_token

    ac, snap = auth_client
    expired = create_access_token(subject=snap["user_id"], tenant_id=snap["tenant_id"], role="tenant_admin", expires_minutes=-1)
    me = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_returns_401(auth_client) -> None:
    ac, _ = auth_client
    me = await ac.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert me.status_code == 401
