"""Schemas for the authentication endpoints."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class LoginResponse(BaseModel):
    """OAuth2 token response: `access_token`, `token_type`, `expires_in` (seconds)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(BaseModel):
    """Public view of a `User` — never expose the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    tenant_id: UUID
    is_active: bool