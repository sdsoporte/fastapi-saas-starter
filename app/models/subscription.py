"""Subscription-plans capability: Plan enum and subscription row."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Plan(str, enum.Enum):
    """Subscription tier — seeded at boot, FK target for tenants."""

    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


PLAN_LIMITS: dict[Plan, dict[str, int | str]] = {
    Plan.FREE: {"max_users": 3, "rate_limit_per_minute": 30, "storage_gb": 1},
    Plan.PRO: {"max_users": 25, "rate_limit_per_minute": 120, "storage_gb": 50},
    Plan.ENTERPRISE: {"max_users": 1000, "rate_limit_per_minute": 600, "storage_gb": 5000},
}


class Subscription(BaseModel):
    """Tenant-to-Plan link with optional expiry."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[Plan] = mapped_column(
        Enum(Plan, name="plan_enum", native_enum=False, length=32),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="subscriptions")
