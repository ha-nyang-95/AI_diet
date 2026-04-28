"""FastAPI Depends — DB 세션, current_user, current_admin (Story 1.2).

토큰 위치 우선순위:
1. `Authorization: Bearer <jwt>` 헤더
2. `bn_access` 쿠키 (Web httpOnly 쿠키)

`current_user`는 user JWT를, `current_admin`은 admin JWT를 검증한다.
혼용 차단(critical): 잘못된 issuer 토큰은 IssuerMismatchError로 차단된다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccessTokenInvalidError,
    AdminRoleRequiredError,
)
from app.core.security import (
    AdminTokenClaims,
    UserTokenClaims,
    verify_admin_token,
    verify_user_token,
)
from app.db.models.user import User


def _extract_token(
    authorization: str | None,
    cookie_token: str | None,
) -> str:
    """Authorization 헤더 우선 → 쿠키 fallback. 없으면 AccessTokenInvalidError.

    `Bearer ` (token이 빈) 또는 잘못된 scheme 헤더는 헤더 자체를 무시하고 쿠키 fallback로 진입
    — 모바일이 헤더 누락 + Web 쿠키 보유 같은 혼합 케이스를 안전하게 처리한다.
    """
    if authorization:
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() == "bearer" and token:
            return token
        # 헤더가 잘못된 형태여도 쿠키 fallback 시도(잘못된 헤더만으로 거부 X).
    if cookie_token:
        return cookie_token
    raise AccessTokenInvalidError("missing access token")


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """`app.state.session_maker`(lifespan에서 init)에서 한 요청 세션을 발급.

    라우터 핸들러에서 예외 발생 시 명시적으로 rollback — connection 상태가 모호해지지 않도록.
    """
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        raise RuntimeError("DB session_maker not initialized in app.state")
    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def current_user_claims(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    bn_access: Annotated[str | None, Cookie()] = None,
) -> UserTokenClaims:
    """user JWT 검증 후 claim 반환 (DB lookup 없음 — claim만 필요한 경로용)."""
    token = _extract_token(authorization, bn_access)
    return verify_user_token(token)


async def current_user(
    db: DbSession,
    claims: Annotated[UserTokenClaims, Depends(current_user_claims)],
) -> User:
    """user JWT 검증 + DB에서 user 로드 (`deleted_at IS NULL` 필터)."""
    result = await db.execute(select(User).where(User.id == claims.sub, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise AccessTokenInvalidError("user not found or deleted")
    return user


async def current_admin_claims(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    bn_admin_access: Annotated[str | None, Cookie()] = None,
) -> AdminTokenClaims:
    """admin JWT 검증 — Authorization 헤더 또는 `bn_admin_access` 쿠키 둘 중 하나."""
    token = _extract_token(authorization, bn_admin_access)
    return verify_admin_token(token)


async def current_admin(
    db: DbSession,
    claims: Annotated[AdminTokenClaims, Depends(current_admin_claims)],
) -> User:
    """admin JWT 검증 + DB에서 user 로드 + role==admin 재확인."""
    result = await db.execute(select(User).where(User.id == claims.sub, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise AccessTokenInvalidError("admin user not found or deleted")
    if user.role != "admin":
        raise AdminRoleRequiredError("admin role required")
    return user
