"""Tests for app.core.security — bcrypt-direct hashing and JWT helpers."""
from __future__ import annotations

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    """bcrypt-direct: no passlib; hash_password + verify_password round-trip."""

    def test_hash_password_returns_bcrypt_string(self) -> None:
        hashed = hash_password("super-secret-password")
        assert hashed.startswith("$2")
        assert len(hashed) >= 59  # bcrypt standard length

    def test_verify_password_accepts_correct_password(self) -> None:
        hashed = hash_password("super-secret-password")
        assert verify_password("super-secret-password", hashed) is True

    def test_verify_password_rejects_wrong_password(self) -> None:
        hashed = hash_password("super-secret-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_password_produces_unique_hashes(self) -> None:
        """bcrypt salts — same input must produce different hashes."""
        h1 = hash_password("same-input")
        h2 = hash_password("same-input")
        assert h1 != h2
        # Both still verify correctly
        assert verify_password("same-input", h1)
        assert verify_password("same-input", h2)


class TestJwtTokens:
    """JWT helpers: encode/decode round-trip + tamper + expiry handling."""

    def test_create_and_decode_access_token(self) -> None:
        token = create_access_token(
            subject="user-uuid",
            tenant_id="tenant-uuid",
            role="tenant_admin",
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "user-uuid"
        assert payload["tenant_id"] == "tenant-uuid"
        assert payload["role"] == "tenant_admin"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_rejects_tampered_signature(self) -> None:
        token = create_access_token(
            subject="user-uuid",
            tenant_id="tenant-uuid",
            role="tenant_admin",
        )
        # Flip a character inside the signature (NOT the last char, which
        # may coincidentally match the replacement byte and yield the same
        # base64 — a previous version of this test was flaky for that reason).
        head, mid, sig = token.split(".")
        replacement = "B" if sig[5] != "B" else "C"
        tampered = f"{head}.{mid}.{sig[:5]}{replacement}{sig[6:]}"
        # Tampered signature must differ from the original
        assert tampered != token, "tampering must change the token"
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_decode_rejects_expired_token(self) -> None:
        token = create_access_token(
            subject="user-uuid",
            tenant_id="tenant-uuid",
            role="tenant_admin",
            expires_minutes=-1,  # already expired
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_decode_rejects_malformed_token(self) -> None:
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token("not.a.jwt")


class TestSecurityModuleSurface:
    """Module re-exports stay stable — guards against rename accidents."""

    def test_exports_expected_helpers(self) -> None:
        from app.core import security

        for name in ("hash_password", "verify_password", "create_access_token", "decode_access_token"):
            assert callable(getattr(security, name))
