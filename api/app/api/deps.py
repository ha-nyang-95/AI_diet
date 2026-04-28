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
    AutomatedDecisionConsentMissingError,
    BasicConsentMissingError,
)
from app.core.security import (
    AdminTokenClaims,
    UserTokenClaims,
    verify_admin_token,
    verify_user_token,
)
from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.legal_documents import CURRENT_VERSIONS


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


def _has_all_basic_consents(row: Consent | None) -> bool:
    """4 timestamp NOT NULL + 4 version이 ``CURRENT_VERSIONS``와 일치인지 확인."""
    if row is None:
        return False
    return (
        row.disclaimer_acknowledged_at is not None
        and row.terms_consent_at is not None
        and row.privacy_consent_at is not None
        and row.sensitive_personal_info_consent_at is not None
        and row.disclaimer_version == CURRENT_VERSIONS["disclaimer"]
        and row.terms_version == CURRENT_VERSIONS["terms"]
        and row.privacy_version == CURRENT_VERSIONS["privacy"]
        and row.sensitive_personal_info_version == CURRENT_VERSIONS["sensitive_personal_info"]
    )


async def require_basic_consents(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> User:
    """4종 기본 동의(disclaimer/terms/privacy/sensitive_personal_info) 통과 + 현재 SOT
    버전 일치 확인.

    인증 게이트(``current_user``)와 분리된 동의 게이트.
    *핵심 사용자 데이터 작성·조회* 라우트(Story 1.5 ``POST /v1/users/me/profile``,
    Story 2.1+ ``/v1/meals/*``)에서 명시 wire한다. ``/v1/users/me`` 같은 자기 정보
    조회 endpoint에 적용 금지(미동의 사용자도 조회 가능해야 UX 정합).
    """
    result = await db.execute(select(Consent).where(Consent.user_id == user.id))
    row = result.scalar_one_or_none()
    if not _has_all_basic_consents(row):
        raise BasicConsentMissingError("basic consents required")
    return user


def has_automated_decision_consent(row: Consent | None) -> bool:
    """Story 1.4 — ``automated_decision_consent_at`` NOT NULL + ``_revoked_at`` IS NULL +
    ``_version`` 일치 3 조건. *기본 동의 선행*은 검증 항목 X(AC4 결정).

    공개 헬퍼 — ``consents.py:_build_status`` 가 응답 모델 결합 boolean 계산에 재사용.
    """
    if row is None:
        return False
    return (
        row.automated_decision_consent_at is not None
        and row.automated_decision_revoked_at is None
        and row.automated_decision_version == CURRENT_VERSIONS["automated-decision"]
    )


async def require_automated_decision_consent(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> User:
    """PIPA 2026.03.15 자동화 의사결정 동의 통과 확인 (Story 1.4).

    Epic 3 분석 라우터(``/v1/analysis/stream`` 등)에서 명시 wire한다. 본 게이트는
    ``require_basic_consents``와 *직교* — 분석 라우터는 두 게이트 모두 wire 권장
    (LLM 비용 0 보호 + 핵심 데이터 정합 검증). 미동의 시 LangGraph/LLM 호출 *전*
    ``AutomatedDecisionConsentMissingError`` raise → 글로벌 핸들러가 RFC 7807 403.

    본 스토리는 라우터에 wire하지 않음 — Epic 3 Story 3.x가 명시 wire.
    """
    result = await db.execute(select(Consent).where(Consent.user_id == user.id))
    row = result.scalar_one_or_none()
    if not has_automated_decision_consent(row):
        raise AutomatedDecisionConsentMissingError("automated decision consent required")
    return user
