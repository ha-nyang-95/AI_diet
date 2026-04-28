"""`/v1/users/me/consents` — 4종 동의 UPSERT + 조회 + 자동화 의사결정 grant/revoke
(Story 1.3, Story 1.4, FR6/FR7).

POST `""`: ``ConsentSubmitRequest`` 4 version 검증 → ``CURRENT_VERSIONS`` 매칭 실패 시
409 ``ConsentVersionMismatchError``. PostgreSQL ``INSERT ... ON CONFLICT (user_id) DO
UPDATE``로 race-free UPSERT (Story 1.2 P11 패턴 정합 — 단일 statement 원자성).
신규 INSERT vs 기존 row UPDATE 구분: PG 시스템 컬럼 ``xmax = 0``이면 INSERT.

GET `""`: 현 사용자의 동의 row 조회. row 없음 → all-null + ``basic_consents_complete:
false``. Story 1.4가 ``automated_decision_*`` 4 필드를 응답 모델에 추가.

POST `/automated-decision` (Story 1.4): PIPA 2026.03.15 자동화 의사결정 동의 grant.
``automated_decision_revoked_at = NULL`` reset(재동의 케이스 안전 처리). 응답 200.
DELETE `/automated-decision` (Story 1.4): 동의 철회. 미동의 row → 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DbSession, current_user
from app.core.exceptions import (
    AutomatedDecisionConsentNotGrantedError,
    AutomatedDecisionConsentVersionMismatchError,
    ConsentVersionMismatchError,
)
from app.db.models.consent import Consent
from app.db.models.user import User
from app.domain.legal_documents import CURRENT_VERSIONS

router = APIRouter()


_USER_AGENT_MAX_LENGTH = 512


# --- Pydantic 스키마 (snake_case 양방향) -----------------------------------


class ConsentSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disclaimer_version: str = Field(min_length=1)
    terms_version: str = Field(min_length=1)
    privacy_version: str = Field(min_length=1)
    sensitive_personal_info_version: str = Field(min_length=1)


class ConsentStatusResponse(BaseModel):
    disclaimer_acknowledged_at: datetime | None
    terms_consent_at: datetime | None
    privacy_consent_at: datetime | None
    sensitive_personal_info_consent_at: datetime | None
    disclaimer_version: str | None
    terms_version: str | None
    privacy_version: str | None
    sensitive_personal_info_version: str | None
    basic_consents_complete: bool

    # Story 1.4 — PIPA 2026.03.15 자동화 의사결정 동의 (별도 게이트).
    automated_decision_consent_at: datetime | None
    automated_decision_revoked_at: datetime | None
    automated_decision_version: str | None
    # ``automated_decision_consent_complete``는 (a) consent_at NOT NULL +
    # (b) revoked_at IS NULL + (c) version 일치 + (d) ``basic_consents_complete``
    # 4 조건 동시 만족. (d)를 결합한 이유: 클라이언트가 단일 boolean으로 분기 가능 +
    # *기본 동의 선행* 의미 강화. 게이트 함수
    # (``require_automated_decision_consent``)는 (a)·(b)·(c)만 검증한다(AC4 결정).
    automated_decision_consent_complete: bool


class AutomatedDecisionGrantRequest(BaseModel):
    """Story 1.4 — POST /v1/users/me/consents/automated-decision body."""

    model_config = ConfigDict(extra="forbid")

    automated_decision_version: str = Field(min_length=1)


# --- helpers ---------------------------------------------------------------


def has_all_basic_consents(row: Consent | None) -> bool:
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


def has_automated_decision_consent(row: Consent | None) -> bool:
    """Story 1.4 — 자동화 의사결정 동의 통과 여부.

    3 조건: (a) ``automated_decision_consent_at`` NOT NULL,
    (b) ``automated_decision_revoked_at`` IS NULL,
    (c) ``automated_decision_version`` 이 ``CURRENT_VERSIONS["automated-decision"]``
    와 일치. *기본 동의 선행*은 라우터 게이트
    (``require_automated_decision_consent``) 검증 항목에 미포함 — 응답 모델
    (``automated_decision_consent_complete``)에서만 결합한다(AC4 결정).
    """
    if row is None:
        return False
    return (
        row.automated_decision_consent_at is not None
        and row.automated_decision_revoked_at is None
        and row.automated_decision_version == CURRENT_VERSIONS["automated-decision"]
    )


def _build_status(row: Consent | None) -> ConsentStatusResponse:
    if row is None:
        return ConsentStatusResponse(
            disclaimer_acknowledged_at=None,
            terms_consent_at=None,
            privacy_consent_at=None,
            sensitive_personal_info_consent_at=None,
            disclaimer_version=None,
            terms_version=None,
            privacy_version=None,
            sensitive_personal_info_version=None,
            basic_consents_complete=False,
            automated_decision_consent_at=None,
            automated_decision_revoked_at=None,
            automated_decision_version=None,
            automated_decision_consent_complete=False,
        )
    basic_complete = has_all_basic_consents(row)
    ad_complete = has_automated_decision_consent(row)
    return ConsentStatusResponse(
        disclaimer_acknowledged_at=row.disclaimer_acknowledged_at,
        terms_consent_at=row.terms_consent_at,
        privacy_consent_at=row.privacy_consent_at,
        sensitive_personal_info_consent_at=row.sensitive_personal_info_consent_at,
        disclaimer_version=row.disclaimer_version,
        terms_version=row.terms_version,
        privacy_version=row.privacy_version,
        sensitive_personal_info_version=row.sensitive_personal_info_version,
        basic_consents_complete=basic_complete,
        automated_decision_consent_at=row.automated_decision_consent_at,
        automated_decision_revoked_at=row.automated_decision_revoked_at,
        automated_decision_version=row.automated_decision_version,
        # AC4 — 응답 필드는 *기본 + AD 모두 통과* 의미를 강화하기 위해 결합 계산.
        automated_decision_consent_complete=basic_complete and ad_complete,
    )


def _validate_versions(body: ConsentSubmitRequest) -> None:
    """4종 basic version 검증 — 첫 mismatch field만 ``latest_versions`` 헤더 인코딩.

    Story 1.4 W13 — 첫 mismatch entry만 ``X-Consent-Latest-Version`` 헤더에
    포함(클라이언트는 GET으로 fresh 텍스트 fetch 시 4종 모두 갱신되므로 다중 entry는
    redundant). 본 helper는 단일 entry dict로 raise.
    """
    if body.disclaimer_version != CURRENT_VERSIONS["disclaimer"]:
        raise ConsentVersionMismatchError(
            "disclaimer version mismatch",
            latest_versions={"disclaimer": CURRENT_VERSIONS["disclaimer"]},
        )
    if body.terms_version != CURRENT_VERSIONS["terms"]:
        raise ConsentVersionMismatchError(
            "terms version mismatch",
            latest_versions={"terms": CURRENT_VERSIONS["terms"]},
        )
    if body.privacy_version != CURRENT_VERSIONS["privacy"]:
        raise ConsentVersionMismatchError(
            "privacy version mismatch",
            latest_versions={"privacy": CURRENT_VERSIONS["privacy"]},
        )
    if body.sensitive_personal_info_version != CURRENT_VERSIONS["sensitive_personal_info"]:
        raise ConsentVersionMismatchError(
            "sensitive_personal_info version mismatch",
            latest_versions={
                "sensitive_personal_info": CURRENT_VERSIONS["sensitive_personal_info"],
            },
        )


def _validate_automated_decision_version(version: str) -> None:
    """Story 1.4 — 단일 필드 version mismatch 시 헤더 entry 첨부."""
    if version != CURRENT_VERSIONS["automated-decision"]:
        raise AutomatedDecisionConsentVersionMismatchError(
            "automated_decision version mismatch",
            latest_versions={
                "automated-decision": CURRENT_VERSIONS["automated-decision"],
            },
        )


def _truncate_user_agent(value: str | None) -> str | None:
    """UTF-8 multibyte 분리 위험 회피 — 바이트 길이 기준 자르기 + invalid byte 무시."""
    if value is None:
        return None
    encoded = value.encode("utf-8")
    if len(encoded) <= _USER_AGENT_MAX_LENGTH:
        return value
    return encoded[:_USER_AGENT_MAX_LENGTH].decode("utf-8", "ignore")


# --- Endpoints -------------------------------------------------------------


@router.post("")
async def submit_consents(
    body: ConsentSubmitRequest,
    request: Request,
    response: Response,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ConsentStatusResponse:
    _validate_versions(body)

    now = datetime.now(UTC)
    ip = request.client.host if request.client else None
    user_agent = _truncate_user_agent(request.headers.get("user-agent"))

    insert_stmt = pg_insert(Consent).values(
        user_id=user.id,
        disclaimer_acknowledged_at=now,
        terms_consent_at=now,
        privacy_consent_at=now,
        sensitive_personal_info_consent_at=now,
        disclaimer_version=body.disclaimer_version,
        terms_version=body.terms_version,
        privacy_version=body.privacy_version,
        sensitive_personal_info_version=body.sensitive_personal_info_version,
        ip_address=ip,
        user_agent=user_agent,
    )
    excluded: Any = insert_stmt.excluded
    upsert_stmt: Any = insert_stmt.on_conflict_do_update(
        index_elements=[Consent.user_id],
        set_={
            "disclaimer_acknowledged_at": excluded.disclaimer_acknowledged_at,
            "terms_consent_at": excluded.terms_consent_at,
            "privacy_consent_at": excluded.privacy_consent_at,
            "sensitive_personal_info_consent_at": excluded.sensitive_personal_info_consent_at,
            "disclaimer_version": excluded.disclaimer_version,
            "terms_version": excluded.terms_version,
            "privacy_version": excluded.privacy_version,
            "sensitive_personal_info_version": excluded.sensitive_personal_info_version,
            "ip_address": excluded.ip_address,
            "user_agent": excluded.user_agent,
            # ON CONFLICT DO UPDATE는 PG 직접 DML이라 SQLAlchemy `onupdate=func.now()`
            # 이벤트가 발화되지 않는다 — set_에 명시해야 재동의 시 갱신 시점이 기록된다.
            "updated_at": func.now(),
        },
    ).returning(literal_column("(xmax = 0)").label("is_inserted"))
    result = await db.execute(upsert_stmt)
    is_inserted = bool(result.scalar_one())
    await db.commit()

    refreshed = await db.execute(select(Consent).where(Consent.user_id == user.id))
    row = refreshed.scalar_one()

    response.status_code = status.HTTP_201_CREATED if is_inserted else status.HTTP_200_OK
    return _build_status(row)


@router.get("")
async def get_consents(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ConsentStatusResponse:
    result = await db.execute(select(Consent).where(Consent.user_id == user.id))
    return _build_status(result.scalar_one_or_none())


# --- Story 1.4 — 자동화 의사결정 동의 grant / revoke -----------------------


@router.post("/automated-decision")
async def grant_automated_decision_consent(
    body: AutomatedDecisionGrantRequest,
    request: Request,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ConsentStatusResponse:
    """PIPA 2026.03.15 자동화 의사결정 동의 grant — 항상 200(부분 update 의미).

    재동의 케이스(이전에 ``automated_decision_revoked_at IS NOT NULL`` 사용자)도 안전:
    UPSERT set_에 ``automated_decision_revoked_at = None``로 명시 reset.
    INSERT 분기(이론상 불가 — 본 endpoint 진입 가드가 basic 4종 통과 강제)에서는 basic
    4 컬럼을 함께 set하지 않는다(``has_all_basic_consents=false`` 반환으로 클라이언트가
    onboarding 흐름 재진입).
    """
    _validate_automated_decision_version(body.automated_decision_version)

    now = datetime.now(UTC)
    ip = request.client.host if request.client else None
    user_agent = _truncate_user_agent(request.headers.get("user-agent"))

    insert_stmt = pg_insert(Consent).values(
        user_id=user.id,
        automated_decision_consent_at=now,
        automated_decision_version=body.automated_decision_version,
        ip_address=ip,
        user_agent=user_agent,
    )
    excluded: Any = insert_stmt.excluded
    upsert_stmt: Any = insert_stmt.on_conflict_do_update(
        index_elements=[Consent.user_id],
        set_={
            "automated_decision_consent_at": excluded.automated_decision_consent_at,
            "automated_decision_version": excluded.automated_decision_version,
            # 재동의 시 철회 시각 명시 reset.
            "automated_decision_revoked_at": None,
            "ip_address": excluded.ip_address,
            "user_agent": excluded.user_agent,
            # ON CONFLICT DO UPDATE는 PG 직접 DML이라 SQLAlchemy ``onupdate=func.now()``
            # 이벤트 미발화(Story 1.3 P2 패턴 정합).
            "updated_at": func.now(),
        },
    )
    await db.execute(upsert_stmt)
    await db.commit()

    refreshed = await db.execute(select(Consent).where(Consent.user_id == user.id))
    return _build_status(refreshed.scalar_one())


@router.delete("/automated-decision")
async def revoke_automated_decision_consent(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> ConsentStatusResponse:
    """동의 철회 — ``automated_decision_revoked_at = now()`` set, ``_consent_at`` 보존.

    row 없음 또는 ``automated_decision_consent_at IS NULL``(미동의) 또는 이미 철회된 상태
    (``automated_decision_revoked_at IS NOT NULL``) →
    ``AutomatedDecisionConsentNotGrantedError`` (404). 이미 철회된 상태에서 재호출 시
    *철회는 idempotent 가 아닌* 명시 분기 — 두 번째 DELETE 가 200 으로 통과하면 원본
    철회 시각(PIPA audit) 을 새 ``now()`` 로 덮어쓴다.
    """
    result = await db.execute(select(Consent).where(Consent.user_id == user.id))
    row = result.scalar_one_or_none()
    if (
        row is None
        or row.automated_decision_consent_at is None
        or row.automated_decision_revoked_at is not None
    ):
        raise AutomatedDecisionConsentNotGrantedError("automated decision consent not granted")

    now = datetime.now(UTC)
    await db.execute(
        update(Consent)
        .where(Consent.user_id == user.id)
        .values(automated_decision_revoked_at=now, updated_at=func.now())
    )
    await db.commit()

    refreshed = await db.execute(select(Consent).where(Consent.user_id == user.id))
    return _build_status(refreshed.scalar_one())
