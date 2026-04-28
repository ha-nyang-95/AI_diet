"""인증·인가 — JWT 발급/검증 + refresh token 유틸 (Story 1.2).

JWT 분리 (절대 통합 금지):
- user JWT: HS256, secret = JWT_USER_SECRET, issuer = JWT_USER_ISSUER, access 30일.
- admin JWT: HS256, secret = JWT_ADMIN_SECRET (다른 값), issuer = JWT_ADMIN_ISSUER,
  access 8시간, refresh 없음.

`verify_*` 함수는 issuer claim을 명시 검증 — 토큰 혼용 차단의 핵심.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import (
    ADMIN_ACCESS_TOKEN_TTL_SECONDS,
    JWT_ADMIN_AUDIENCE,
    JWT_USER_AUDIENCE,
    USER_ACCESS_TOKEN_TTL_SECONDS,
    settings,
)
from app.core.exceptions import (
    AccessTokenExpiredError,
    AccessTokenInvalidError,
    AdminRoleRequiredError,
    IssuerMismatchError,
)

JWT_ALGORITHM: Final[str] = "HS256"
ALLOWED_PLATFORMS: Final[frozenset[str]] = frozenset({"mobile", "web"})
# 분산 환경 NTP 드리프트 흡수 — exp/iat 검증 시 ±60s 허용.
JWT_LEEWAY_SECONDS: Final[int] = 60


def _safe_uuid(value: Any, *, error: type[Exception], message: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise error(message) from exc


def _safe_timestamp(value: Any, *, error: type[Exception], message: str) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise error(message) from exc


@dataclass(frozen=True, slots=True)
class UserTokenClaims:
    sub: uuid.UUID
    role: str
    platform: str
    issuer: str
    audience: str
    expires_at: datetime
    issued_at: datetime
    jti: str


@dataclass(frozen=True, slots=True)
class AdminTokenClaims:
    sub: uuid.UUID
    role: str
    issuer: str
    audience: str
    expires_at: datetime
    issued_at: datetime
    jti: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_user_token(
    user_id: uuid.UUID,
    role: str,
    platform: str,
    *,
    now: datetime | None = None,
) -> str:
    """user access JWT 발급. role ∈ {user, admin}, platform ∈ {mobile, web}."""
    if platform not in ALLOWED_PLATFORMS:
        raise ValueError(f"invalid platform: {platform!r}")
    if role not in {"user", "admin"}:
        raise ValueError(f"invalid role: {role!r}")

    now_dt = now or _utcnow()
    expires_at = now_dt + timedelta(seconds=USER_ACCESS_TOKEN_TTL_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": settings.jwt_user_issuer,
        "aud": JWT_USER_AUDIENCE,
        "iat": int(now_dt.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
        "role": role,
        "platform": platform,
    }
    encoded: str = jwt.encode(payload, settings.jwt_user_secret, algorithm=JWT_ALGORITHM)
    return encoded


def verify_user_token(token: str) -> UserTokenClaims:
    """user JWT 검증 — issuer/audience/exp/role/algorithm 모두 enforcement.

    실패 시 도메인 예외:
    - 만료 → AccessTokenExpiredError
    - issuer 불일치 → IssuerMismatchError
    - 그 외 (서명/audience/형식) → AccessTokenInvalidError
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_user_secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_USER_AUDIENCE,
            options={
                "require": ["exp", "iat", "iss", "sub", "role", "jti"],
                "leeway": JWT_LEEWAY_SECONDS,
            },
        )
    except ExpiredSignatureError as exc:
        raise AccessTokenExpiredError("access token expired") from exc
    except JWTError as exc:
        raise AccessTokenInvalidError(f"access token invalid: {exc}") from exc

    issuer = payload.get("iss")
    if issuer != settings.jwt_user_issuer:
        raise IssuerMismatchError(f"expected issuer {settings.jwt_user_issuer!r}, got {issuer!r}")

    role = payload.get("role")
    if role not in {"user", "admin"}:
        raise AccessTokenInvalidError(f"invalid role claim: {role!r}")

    platform = str(payload.get("platform", ""))
    if platform not in ALLOWED_PLATFORMS:
        raise AccessTokenInvalidError(f"invalid platform claim: {platform!r}")

    return UserTokenClaims(
        sub=_safe_uuid(
            payload.get("sub"), error=AccessTokenInvalidError, message="invalid sub claim"
        ),
        role=str(role),
        platform=platform,
        issuer=str(issuer),
        audience=str(payload.get("aud")),
        expires_at=_safe_timestamp(
            payload.get("exp"), error=AccessTokenInvalidError, message="invalid exp claim"
        ),
        issued_at=_safe_timestamp(
            payload.get("iat"), error=AccessTokenInvalidError, message="invalid iat claim"
        ),
        jti=str(payload["jti"]),
    )


def create_admin_token(user_id: uuid.UUID, *, now: datetime | None = None) -> str:
    """admin access JWT 발급 — 8시간, refresh 없음."""
    now_dt = now or _utcnow()
    expires_at = now_dt + timedelta(seconds=ADMIN_ACCESS_TOKEN_TTL_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": settings.jwt_admin_issuer,
        "aud": JWT_ADMIN_AUDIENCE,
        "iat": int(now_dt.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
        "role": "admin",
    }
    encoded: str = jwt.encode(payload, settings.jwt_admin_secret, algorithm=JWT_ALGORITHM)
    return encoded


def verify_admin_token(token: str) -> AdminTokenClaims:
    """admin JWT 검증 — admin secret + admin issuer + role==admin."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_admin_secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_ADMIN_AUDIENCE,
            options={
                "require": ["exp", "iat", "iss", "sub", "role", "jti"],
                "leeway": JWT_LEEWAY_SECONDS,
            },
        )
    except ExpiredSignatureError as exc:
        raise AccessTokenExpiredError("admin token expired") from exc
    except JWTError as exc:
        raise AccessTokenInvalidError(f"admin token invalid: {exc}") from exc

    issuer = payload.get("iss")
    if issuer != settings.jwt_admin_issuer:
        raise IssuerMismatchError(f"expected issuer {settings.jwt_admin_issuer!r}, got {issuer!r}")

    if payload.get("role") != "admin":
        raise AdminRoleRequiredError("admin role required")

    return AdminTokenClaims(
        sub=_safe_uuid(
            payload.get("sub"), error=AccessTokenInvalidError, message="invalid sub claim"
        ),
        role="admin",
        issuer=str(issuer),
        audience=str(payload.get("aud")),
        expires_at=_safe_timestamp(
            payload.get("exp"), error=AccessTokenInvalidError, message="invalid exp claim"
        ),
        issued_at=_safe_timestamp(
            payload.get("iat"), error=AccessTokenInvalidError, message="invalid iat claim"
        ),
        jti=str(payload["jti"]),
    )


def create_refresh_token() -> tuple[str, str]:
    """opaque refresh token + sha256 hash 반환. plaintext는 클라이언트에만 전달.

    DB에는 sha256 hash만 저장(평문 저장 금지 — NFR-S1).
    """
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_refresh_token(plaintext)


def hash_refresh_token(token: str) -> str:
    """refresh token plaintext의 sha256 hex (64자)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
