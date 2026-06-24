"""Tenant entity — root of every multi-tenant query."""
from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user import User


SLUG_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")


class TenantStatus(str, enum.Enum):
    """A suspended tenant cannot log in but data is preserved."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class Tenant(BaseModel):
    """A SaaS customer organisation."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        Index("ix_tenants_slug", "slug"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status_enum", native_enum=False, length=16),
        nullable=False,
        default=TenantStatus.ACTIVE,
    )

    users: Mapped[list[User]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="tenant", cascade="all, delete-orphan"
    )
