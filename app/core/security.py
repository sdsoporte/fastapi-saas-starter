"""Password hashing and JWT helpers.

Uses `bcrypt` directly (no passlib — unmaintained) and `pyjwt[crypto]`
for JWT. Tokens carry `sub`, `tenant_id`, `role`, `iat`, `exp`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

# --- Password hashing ---


def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt (cost factor 12)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time compare a plain password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# --- JWT helpers ---


def create_access_token(
    *,
    subject: str,
    tenant_id: str,
    role: str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Encode a signed JWT carrying sub / tenant_id / role / iat / exp."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    expire = now + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify a JWT. Raises jwt errors on tamper / expiry."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
