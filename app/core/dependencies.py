"""Shared FastAPI dependencies — OAuth2 scheme and current-user resolver.

PR 2 scope: `oauth2_scheme` + `get_current_user` (with suspended checks).
`require_role` and `TenantScopedSession` are Phase 3 concerns.
"""
from __future__ import annotations

from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_db
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


def _credentials(detail: str = "Invalid credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve a `User` from a bearer JWT; reject missing/invalid/suspended."""
    if not token:
        raise _credentials("Not authenticated")

    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError as exc:
        raise _credentials("Token expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise _credentials("Invalid token") from exc

    sub = payload.get("sub")
    tenant_claim = payload.get("tenant_id")
    if not sub or not tenant_claim:
        raise _credentials("Invalid token")

    # Trust the JWT's sub + tenant_id pair; verify they still resolve.
    user = (
        await db.execute(select(User).where(User.id == sub))
    ).scalar_one_or_none()
    if not user:
        raise _credentials("Invalid token")

    if not user.is_active:
        raise _credentials("User suspended")

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one_or_none()
    if tenant is None or tenant.status == TenantStatus.SUSPENDED:
        raise _credentials("Tenant suspended")

    return user