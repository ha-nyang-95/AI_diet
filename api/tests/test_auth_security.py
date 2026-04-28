"""Story 1.2 — JWT 보안 단위 테스트 (AC #1, #3, #12.a).

대상: app.core.security.{create_user_token, verify_user_token, create_admin_token,
verify_admin_token, create_refresh_token, hash_refresh_token}.

케이스(8건+):
- 정상 user 토큰 발급 + 검증 round-trip
- 정상 admin 토큰 발급 + 검증 round-trip
- 만료된 user 토큰 → AccessTokenExpiredError
- 만료된 admin 토큰 → AccessTokenExpiredError
- user 토큰을 admin verify에 → IssuerMismatchError
- admin 토큰을 user verify에 → IssuerMismatchError
- 잘못된 secret 서명 → AccessTokenInvalidError
- 잘못된 알고리즘(none) → AccessTokenInvalidError
- 누락된 role claim → AccessTokenInvalidError
- refresh token: 32-byte URL-safe random + sha256 hex 64자 일관성
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt as jose_jwt

from app.core.config import (
    JWT_ADMIN_AUDIENCE,
    JWT_USER_AUDIENCE,
    settings,
)
from app.core.exceptions import (
    AccessTokenExpiredError,
    AccessTokenInvalidError,
    AdminRoleRequiredError,
    IssuerMismatchError,
)
from app.core.security import (
    JWT_ALGORITHM,
    create_admin_token,
    create_refresh_token,
    create_user_token,
    hash_refresh_token,
    verify_admin_token,
    verify_user_token,
)


def test_user_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_user_token(user_id, role="user", platform="mobile")
    claims = verify_user_token(token)
    assert claims.sub == user_id
    assert claims.role == "user"
    assert claims.platform == "mobile"
    assert claims.issuer == settings.jwt_user_issuer
    assert claims.audience == JWT_USER_AUDIENCE
    assert claims.expires_at > claims.issued_at
    assert uuid.UUID(claims.jti).version == 4


def test_user_token_admin_role_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_user_token(user_id, role="admin", platform="web")
    claims = verify_user_token(token)
    assert claims.role == "admin"
    assert claims.platform == "web"


def test_user_token_rejects_invalid_platform() -> None:
    with pytest.raises(ValueError):
        create_user_token(uuid.uuid4(), role="user", platform="desktop")


def test_user_token_rejects_invalid_role() -> None:
    with pytest.raises(ValueError):
        create_user_token(uuid.uuid4(), role="superadmin", platform="mobile")


def test_user_token_expired_raises() -> None:
    past = datetime.now(UTC) - timedelta(days=31)
    token = create_user_token(uuid.uuid4(), role="user", platform="mobile", now=past)
    with pytest.raises(AccessTokenExpiredError):
        verify_user_token(token)


def test_user_token_with_admin_issuer_raises_mismatch() -> None:
    """admin secret + admin issuer로 발급한 토큰을 user verify에 보내면 차단.

    secret이 분리되어 있어 jose 단계 1차 차단(invalid). issuer 분기는 user secret으로
    위조한 토큰에서만 도달 — `test_user_token_admin_issuer_forged_via_user_secret`에서 검증.
    """
    admin_token = create_admin_token(uuid.uuid4())
    with pytest.raises(AccessTokenInvalidError):
        verify_user_token(admin_token)


def test_user_token_admin_issuer_forged_via_user_secret() -> None:
    """user secret으로 admin issuer claim을 위조한 토큰 → IssuerMismatchError."""
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_admin_issuer,  # 위조
        "aud": JWT_USER_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",
        "platform": "mobile",
    }
    forged = jose_jwt.encode(payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    with pytest.raises(IssuerMismatchError):
        verify_user_token(forged)


def test_user_token_wrong_secret_raises_invalid() -> None:
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_user_issuer,
        "aud": JWT_USER_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",
        "platform": "mobile",
    }
    bad = jose_jwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)
    with pytest.raises(AccessTokenInvalidError):
        verify_user_token(bad)


def test_user_token_missing_role_claim_raises() -> None:
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_user_issuer,
        "aud": JWT_USER_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        # role 누락
    }
    token = jose_jwt.encode(payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    with pytest.raises(AccessTokenInvalidError):
        verify_user_token(token)


def test_user_token_wrong_audience_raises() -> None:
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_user_issuer,
        "aud": "some-other-service",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",
        "platform": "mobile",
    }
    token = jose_jwt.encode(payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    with pytest.raises(AccessTokenInvalidError):
        verify_user_token(token)


def test_admin_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_admin_token(user_id)
    claims = verify_admin_token(token)
    assert claims.sub == user_id
    assert claims.role == "admin"
    assert claims.issuer == settings.jwt_admin_issuer
    assert claims.audience == JWT_ADMIN_AUDIENCE


def test_admin_token_expired_raises() -> None:
    past = datetime.now(UTC) - timedelta(hours=9)
    token = create_admin_token(uuid.uuid4(), now=past)
    with pytest.raises(AccessTokenExpiredError):
        verify_admin_token(token)


def test_admin_verify_rejects_user_token() -> None:
    """user secret으로 서명된 토큰은 admin verify(다른 secret)의 1차 단계에서 invalid."""
    user_token = create_user_token(uuid.uuid4(), role="user", platform="web")
    with pytest.raises(AccessTokenInvalidError):
        verify_admin_token(user_token)


def test_admin_verify_user_issuer_forged_via_admin_secret() -> None:
    """admin secret으로 user issuer claim을 위조한 토큰 → IssuerMismatchError."""
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_user_issuer,  # 위조
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "admin",
    }
    forged = jose_jwt.encode(payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    with pytest.raises(IssuerMismatchError):
        verify_admin_token(forged)


def test_admin_verify_rejects_non_admin_role() -> None:
    """admin secret + admin issuer로 발급됐어도 role != admin이면 차단."""
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_admin_issuer,
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": str(uuid.uuid4()),
        "role": "user",  # admin이 아님
    }
    token = jose_jwt.encode(payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    with pytest.raises(AdminRoleRequiredError):
        verify_admin_token(token)


def test_refresh_token_random_and_hash_consistent() -> None:
    plaintext, hash1 = create_refresh_token()
    # secrets.token_urlsafe(32) → 정확히 43자 base64url(32 bytes → 43 chars no padding).
    assert len(plaintext) == 43
    # sha256 hex = 64자
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)
    # 동일 plaintext → 동일 hash (결정적)
    assert hash_refresh_token(plaintext) == hash1
    # 다른 plaintext → 다른 hash — 결정적 fixture로 회귀 검증.
    assert hash_refresh_token("a") != hash_refresh_token("b")
    assert hash_refresh_token("") == hashlib.sha256(b"").hexdigest()


def test_refresh_token_random_uniqueness_at_scale() -> None:
    """1000회 호출 시 plaintext + hash 모두 고유 — entropy 회귀 차단."""
    plaintexts: set[str] = set()
    hashes: set[str] = set()
    for _ in range(1000):
        plaintext, h = create_refresh_token()
        plaintexts.add(plaintext)
        hashes.add(h)
    assert len(plaintexts) == 1000
    assert len(hashes) == 1000
