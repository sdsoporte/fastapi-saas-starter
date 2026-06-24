"""Auth router: POST /auth/login + GET /auth/me.

`POST /auth/login` accepts `application/x-www-form-urlencoded` per OAuth2
password flow. Timing is equalised so unknown-email and wrong-password take
roughly the same wall clock (a dummy bcrypt check runs when no user is found).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginResponse, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """Authenticate email + password, return a JWT."""
    settings = get_settings()

    user = (
        await db.execute(select(User).where(User.email == form.username))
    ).scalar_one_or_none()

    # Run a bcrypt compare either way so timing doesn't leak which side
    # was wrong. Real users compare against their hash; unknowns compare
    # against a synthetic hash.
    sentinel_hash = (
        "$2b$12$CwTycUXWue0Thq9StjUM0uJ8.5b3yM8Ic0wEWaHbm7Ew0rLp3eKSu"
    )
    if user is None:
        verify_password(form.password, sentinel_hash)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        subject=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role.value,
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserRead)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    """Return the user identified by the bearer token."""
    return UserRead.model_validate(current_user)