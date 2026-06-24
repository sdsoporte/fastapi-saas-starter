"""Tests for app.models — Tenant, User, Subscription, Plan schemas and enums."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.base import BaseModel
from app.models.subscription import Plan, Subscription
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User, UserRole


class TestEnums:
    """Role and status enums must have the values declared by the design."""

    def test_user_role_values(self) -> None:
        assert UserRole.SUPER_ADMIN.value == "super_admin"
        assert UserRole.TENANT_ADMIN.value == "tenant_admin"
        assert UserRole.TENANT_USER.value == "tenant_user"

    def test_tenant_status_values(self) -> None:
        assert TenantStatus.ACTIVE.value == "active"
        assert TenantStatus.SUSPENDED.value == "suspended"

    def test_plan_values(self) -> None:
        assert Plan.FREE.value == "FREE"
        assert Plan.PRO.value == "PRO"
        assert Plan.ENTERPRISE.value == "ENTERPRISE"


class TestTenantModel:
    """Tenant table schema and persistence behavior."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_tenant(self, db_session) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        db_session.add(tenant)
        await db_session.flush()
        assert isinstance(tenant.id, UUID)
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.created_at is not None
        assert isinstance(tenant.created_at, datetime)

        fetched = (await db_session.execute(select(Tenant).where(Tenant.slug == "acme"))).scalar_one()
        assert fetched.name == "Acme"

    @pytest.mark.asyncio
    async def test_tenant_slug_must_be_unique(self, db_session) -> None:
        db_session.add(Tenant(name="Acme", slug="acme"))
        await db_session.flush()
        db_session.add(Tenant(name="Acme 2", slug="acme"))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_tenant_inherits_from_base_model(self) -> None:
        assert issubclass(Tenant, BaseModel)


class TestUserModel:
    """User table schema, role enum binding, tenant FK."""

    @pytest.mark.asyncio
    async def test_create_user_under_tenant(self, db_session) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        db_session.add(tenant)
        await db_session.flush()

        user = User(
            tenant_id=tenant.id,
            email="alice@acme.com",
            hashed_password="x" * 60,
            role=UserRole.TENANT_ADMIN,
        )
        db_session.add(user)
        await db_session.flush()

        assert isinstance(user.id, UUID)
        assert user.is_active is True
        assert user.role == UserRole.TENANT_ADMIN

        fetched = (
            await db_session.execute(select(User).where(User.email == "alice@acme.com"))
        ).scalar_one()
        assert fetched.tenant_id == tenant.id

    @pytest.mark.asyncio
    async def test_user_email_unique_within_tenant(self, db_session) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        db_session.add(tenant)
        await db_session.flush()

        db_session.add(
            User(
                tenant_id=tenant.id,
                email="bob@acme.com",
                hashed_password="x" * 60,
                role=UserRole.TENANT_USER,
            )
        )
        await db_session.flush()

        db_session.add(
            User(
                tenant_id=tenant.id,
                email="bob@acme.com",
                hashed_password="y" * 60,
                role=UserRole.TENANT_USER,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_user_inherits_from_base_model(self) -> None:
        assert issubclass(User, BaseModel)


class TestSubscriptionModel:
    """Subscription row links a Tenant to a Plan with optional expiry."""

    @pytest.mark.asyncio
    async def test_create_subscription_for_tenant(self, db_session) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        db_session.add(tenant)
        await db_session.flush()

        sub = Subscription(tenant_id=tenant.id, plan=Plan.ENTERPRISE, active=True)
        db_session.add(sub)
        await db_session.flush()

        assert isinstance(sub.id, UUID)
        assert sub.active is True
        assert sub.plan == Plan.ENTERPRISE


class TestModelMetadata:
    """Sanity: every model is registered with Base.metadata."""

    def test_all_tables_present(self) -> None:
        tables = set(BaseModel.metadata.tables.keys())
        assert "tenants" in tables
        assert "users" in tables
        assert "subscriptions" in tables
