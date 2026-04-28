"""`/v1/users/me/consents` — 4종 동의 UPSERT + 조회 (Story 1.3, FR6/FR7).

POST: ``ConsentSubmitRequest`` 4 version 검증 → ``CURRENT_VERSIONS`` 매칭 실패 시
409 ConsentVersionMismatchError. PostgreSQL ``INSERT ... ON CONFLICT (user_id) DO
UPDATE``로 race-free UPSERT (Story 1.2 P11 패턴 정합 — 단일 statement 원자성).

신규 INSERT vs 기존 row UPDATE 구분: PG 시스템 컬럼 ``xmax = 0``이면 INSERT, 그 외는
UPDATE. 응답 status 201 / 200을 정확히 구분하기 위함.

GET: 현 사용자의 동의 row 조회. row 없음 → all-null + ``basic_consents_complete: false``.

Story 1.4가 같은 라우터 파일에 자동화 의사결정 토글 endpoint를 추가한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import DbSession, current_user
from app.core.exceptions import ConsentVersionMismatchError
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
        )
    return ConsentStatusResponse(
        disclaimer_acknowledged_at=row.disclaimer_acknowledged_at,
        terms_consent_at=row.terms_consent_at,
        privacy_consent_at=row.privacy_consent_at,
        sensitive_personal_info_consent_at=row.sensitive_personal_info_consent_at,
        disclaimer_version=row.disclaimer_version,
        terms_version=row.terms_version,
        privacy_version=row.privacy_version,
        sensitive_personal_info_version=row.sensitive_personal_info_version,
        basic_consents_complete=has_all_basic_consents(row),
    )


def _validate_versions(body: ConsentSubmitRequest) -> None:
    if body.disclaimer_version != CURRENT_VERSIONS["disclaimer"]:
        raise ConsentVersionMismatchError("disclaimer version mismatch")
    if body.terms_version != CURRENT_VERSIONS["terms"]:
        raise ConsentVersionMismatchError("terms version mismatch")
    if body.privacy_version != CURRENT_VERSIONS["privacy"]:
        raise ConsentVersionMismatchError("privacy version mismatch")
    if body.sensitive_personal_info_version != CURRENT_VERSIONS["sensitive_personal_info"]:
        raise ConsentVersionMismatchError("sensitive_personal_info version mismatch")


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
