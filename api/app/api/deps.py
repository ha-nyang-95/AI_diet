"""FastAPI Depends — DB 세션, current_user, current_admin (Story 1.2).

토큰 위치 우선순위:
1. `Authorization: Bearer <jwt>` 헤더
2. `bn_access` 쿠키 (Web httpOnly 쿠키)

`current_user`는 user JWT를, `current_admin`은 admin JWT를 검증한다.
혼용 차단(critical): 잘못된 issuer 토큰은 IssuerMismatchError로 차단된다.

Story 7.3 추가 — ``audit_admin_action(action, target_resource=None)`` factory
Dependency. admin endpoint 데코레이터 ``dependencies=[Depends(audit_admin_action(...))]``
wire 시 transitive ``Depends(current_admin)`` 자동 연쇄 + audit row INSERT.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccessTokenInvalidError,
    AdminIpBlockedError,
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
from app.db.models.audit_log import AuditLogAction
from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.legal_documents import (
    CURRENT_VERSION_TYPES,
    CURRENT_VERSIONS,
    X_CONSENT_UPDATE_AVAILABLE_HEADER,
)


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


async def require_admin_ip_allowed(
    request: Request,
    claims: Annotated[AdminTokenClaims, Depends(current_admin_claims)],
) -> AdminTokenClaims:
    """Story 7.1 — admin JWT 검증 *직후* IP 화이트리스트 검사. 미통과 시 403.

    JWT 검증 → IP 검증 → DB role 재확인(``current_admin``) 3-tier chain의 2번째 게이트.
    ``ADMIN_IP_ALLOWLIST``가 빈 list(MVP default)이면 graceful pass — NFR-S8 정합.

    Story 7.1 CR — ``current_admin``이 본 dep을 transitively 포함하도록 체인 재구성
    (Story 7.2/7.4가 ``Depends(current_admin)``만 wire해도 IP 가드 자동 적용).

    순환 import 회피 — ``settings``/``check_admin_ip_allowed``는 함수 내 lazy import.
    """
    from app.core.config import settings
    from app.core.proxy import check_admin_ip_allowed

    if not check_admin_ip_allowed(request, settings.admin_ip_allowlist):
        raise AdminIpBlockedError("admin endpoint accessed from non-allowlisted IP")
    return claims


async def current_admin(
    db: DbSession,
    claims: Annotated[AdminTokenClaims, Depends(require_admin_ip_allowed)],
) -> User:
    """admin JWT 검증 + IP 가드 + DB에서 user 로드 + role==admin 재확인.

    Story 7.1 CR — IP 가드를 transitive dep으로 포함해 *모든* admin endpoint가
    ``Depends(current_admin)``만 wire해도 NFR-S8 자동 적용 (Story 7.2/7.4 forward-compat).
    """
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


# Story 3.9 AC4 — major / minor 버전 분기.
# - 4 timestamp 중 하나라도 NULL → 동의 미진행, 차단(major).
# - version mismatch 중 하나라도 ``CURRENT_VERSION_TYPES[doc]=="major"`` → 차단.
# - 모든 mismatch가 ``"minor"`` → 통과 + ``X-Consent-Update-Available`` 헤더 첨부.
def _check_basic_consents(row: Consent | None) -> tuple[bool, dict[str, str]]:
    """``(passed, minor_updates)``. minor_updates: ``doc_key → latest_version``."""
    if row is None:
        return False, {}
    if (
        row.disclaimer_acknowledged_at is None
        or row.terms_consent_at is None
        or row.privacy_consent_at is None
        or row.sensitive_personal_info_consent_at is None
    ):
        return False, {}

    minor_updates: dict[str, str] = {}
    has_major_mismatch = False
    for doc_key, attr in (
        ("disclaimer", "disclaimer_version"),
        ("terms", "terms_version"),
        ("privacy", "privacy_version"),
        ("sensitive_personal_info", "sensitive_personal_info_version"),
    ):
        user_version = getattr(row, attr)
        latest = CURRENT_VERSIONS[doc_key]
        if user_version != latest:
            # default ``"major"`` fallback — 키 누락 시 안전 측 차단.
            if CURRENT_VERSION_TYPES.get(doc_key, "major") == "major":
                has_major_mismatch = True
            else:
                minor_updates[doc_key] = latest

    if has_major_mismatch:
        return False, {}

    # CR P17 (2026-05-06) — ``sensitive_personal_info``는 ``privacy``와 본문/version을
    # 공유(``CURRENT_VERSION_TYPES`` 코멘트 정합). 같은 version으로 동시 mismatch 시
    # ``X-Consent-Update-Available`` 헤더에 *동일 정보 중복 표기*를 회피 — privacy를
    # canonical로 노출(클라이언트 banner 1회만 표시).
    if (
        "privacy" in minor_updates
        and "sensitive_personal_info" in minor_updates
        and minor_updates["privacy"] == minor_updates["sensitive_personal_info"]
    ):
        del minor_updates["sensitive_personal_info"]

    return True, minor_updates


async def require_basic_consents(
    response: Response,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> User:
    """4종 기본 동의(disclaimer/terms/privacy/sensitive_personal_info) 통과 + 현재 SOT
    버전 일치 확인.

    인증 게이트(``current_user``)와 분리된 동의 게이트.
    *핵심 사용자 데이터 작성·조회* 라우트(Story 1.5 ``POST /v1/users/me/profile``,
    Story 2.1+ ``/v1/meals/*``)에서 명시 wire한다.

    ``/v1/users/me``, ``/v1/users/me/profile`` GET 같은 *자기 정보 조회* endpoint에
    적용 금지: PIPA Art.35(정보주체의 권리 — 열람·정정·삭제·처리정지)는 동의 철회와
    독립된 *권리*로 보장되며, 자기 데이터 조회를 동의 게이트로 차단하면 권리 행사
    자체가 봉쇄된다(+ UX 모순: 자기가 입력한 데이터를 볼 수 없음). 따라서 *작성*
    경로(POST/PATCH/DELETE)는 동의 게이트 wire, *조회* 경로(GET)는 인증만 wire.
    """
    result = await db.execute(select(Consent).where(Consent.user_id == user.id))
    row = result.scalar_one_or_none()
    passed, minor_updates = _check_basic_consents(row)
    if not passed:
        raise BasicConsentMissingError("basic consents required")
    if minor_updates:
        # ``doc_key=version,...`` 인코딩(comma-separated). 모바일/Web 클라이언트가
        # 헤더를 읽고 banner로 사용자 안내(banner UI는 Story 8.6 forward-compat).
        encoded = ",".join(f"{k}={v}" for k, v in minor_updates.items())
        response.headers[X_CONSENT_UPDATE_AVAILABLE_HEADER] = encoded
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


def audit_admin_action(
    *,
    action: AuditLogAction,
    target_resource: str | None = None,
) -> Callable[..., Awaitable[None]]:
    """관리자 액션 audit log 자동 기록 factory Dependency (Story 7.3, FR37).

    반환된 dep은 ``Depends(current_admin)``을 transitive 포함 — admin 토큰 없거나
    IP 가드 차단되거나 role!=admin이면 ``current_admin`` 단계에서 raise되어 audit
    INSERT는 *미발동*(epics.md:914 *"admin_user_jwt_required ↔ audit_admin_action
    자동 연쇄"* 정합).

    FastAPI dep cache 정합: 핸들러 시그니처에 ``Depends(current_admin)``가 이미
    있어도 같은 request scope에서 한 번만 실행됨(dep cache 표준 동작) — DB 재조회
    비용 0.

    path param 자동 추출:
    - ``user_id`` 경로 변수 → ``target_user_id``(UUID parsing 실패 시 None).
    - ``meal_id`` 경로 변수 → ``target_resource_id``(UUID parsing 실패 시 None).
    - 그 외 path param은 향후 endpoint별 add-on 시 본 dep 확장(YAGNI: 현 6 endpoint는
      ``user_id``/``meal_id``로 충분).

    실패 격리(critical): audit INSERT 자체 실패(DB error/connection drop)는 *fail-open
    + log.error*. 사유 — admin business action을 audit infra 일시 장애로 차단하면
    거버넌스 가용성(B3 KPI) 위반 + audit DB 분리 시점(Story 8) 이전 단계에서 단일
    DB 가용성 risk 흡수. Sentry로 운영 알림 + structlog ERROR + 본 함수는 silent
    return(요청 진행). 단, *DB integrity error*(예: ENUM 값 mismatch — 본 모듈
    enum과 alembic ENUM SOT 정합 자동 보장)는 deployment 직전 회귀 가드(AC6)로 사전
    차단(런타임 분기 도달 0).
    """

    async def _dep(
        request: Request,
        admin: Annotated[User, Depends(current_admin)],
        db: DbSession,
    ) -> None:
        # lazy import — 순환 의존(deps ↔ services) 회피
        from app.services.audit_service import record_admin_action  # noqa: PLC0415

        await record_admin_action(
            db,
            request=request,
            admin=admin,
            action=action,
            target_resource=target_resource,
        )

    return _dep
