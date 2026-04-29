"""``/v1/meals`` — 식단 텍스트·사진 입력 + CRUD (Story 2.1 + Story 2.2).

4 endpoint:
- ``POST /v1/meals``                — 식단 생성 (require_basic_consents)
- ``GET /v1/meals``                 — 자기 식단 목록 조회 (인증만 — PIPA Art.35)
- ``PATCH /v1/meals/{meal_id}``     — 식단 수정 (require_basic_consents)
- ``DELETE /v1/meals/{meal_id}``    — soft delete (require_basic_consents)

핵심 결정:
- *작성 경로*(POST/PATCH/DELETE)에만 ``Depends(require_basic_consents)`` wire.
  *조회 경로*(GET)는 ``current_user``만 — PIPA Art.35 정보주체 권리 (자기 데이터
  열람은 동의 철회와 독립).
- PATCH/DELETE는 *소유권 미일치 / 존재 X / 이미 soft-deleted* 모두 같은 응답
  (404 + ``code=meals.not_found``) — enumeration 차단.
- 단일 SQL ``update().where(id, user_id, deleted_at IS NULL).returning(Meal)``로
  race-free + 소유권 + soft-delete 검증 통합 (Story 1.5 ``users.py:177-194`` 패턴).
- DB-side ``func.now()`` 단일 시계 — Python ``datetime.now()`` 회피.
- soft delete만 — 30일 grace + 물리 파기는 Story 5.2 책임.
- ``Idempotency-Key`` 헤더는 *수신 허용* (CORS 등록), *처리는 Story 2.5*.
- ``raw_text`` *내용*은 로그에 raw 출력 X — ``raw_text_len``만 forward (NFR-S5).

Story 2.2 추가:
- ``image_key`` (R2 object key) 필드 추가 — `MealCreateRequest`/`MealUpdateRequest`/
  `MealResponse` 모두 nullable. ``raw_text`` NOT NULL invariant 유지 — 사진-only
  입력 시 서버가 ``"(사진 입력)"`` placeholder fallback (Story 2.3 OCR이 결과로
  덮어씀).
- 최소 1 입력(`raw_text` 또는 `image_key`) — POST `model_validator`로 강제.
- `image_key.startswith(f"meals/{user.id}/")` ownership 검증 — cross-user 도용 차단
  (라우터 inline, Pydantic field_validator는 user context 미접근).
- `MealResponse.image_url` derive — `r2_public_base_url` 기반 public CDN URL.
- PATCH는 `image_key=null` 명시 송신 시 *클리어*, 키 부재 시 *no-op*
  (Pydantic v2 `model_fields_set`로 absent vs explicit null 구분).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, insert, select, update

from app.adapters import r2 as r2_adapter
from app.api.deps import DbSession, current_user, require_basic_consents
from app.core.exceptions import (
    MealImageOwnershipError,
    MealNotFoundError,
    MealQueryValidationError,
)
from app.db.models.meal import Meal
from app.db.models.user import User

# 사진-only 입력 시 ``raw_text`` 자동 fallback. Story 2.3 OCR이 추출 결과로 덮어씀.
# i18n은 OUT (NFR-L2 한국어 1차).
PHOTO_ONLY_RAW_TEXT_PLACEHOLDER = "(사진 입력)"

logger = structlog.get_logger(__name__)

router = APIRouter()


# --- Pydantic 스키마 (snake_case 양방향) -----------------------------------


def _reject_naive_ate_at(v: datetime | None) -> datetime | None:
    """``ate_at`` naive datetime 거부 (P19 / D3 결정).

    Postgres ``timestamptz``가 naive datetime을 *세션 TZ*로 해석 → 같은 ``"12:00"``
    문자열이 클라이언트 TZ별로 다른 절대 시각으로 저장되는 wire 모호성 차단. 모바일
    ``Date.toISOString()``는 항상 ``Z``-suffixed UTC 송신 → 정상 클라이언트 영향 0.
    """
    if v is not None and v.tzinfo is None:
        raise ValueError("ate_at must include a timezone (e.g., '2026-04-29T12:00:00+09:00')")
    return v


class MealCreateRequest(BaseModel):
    """``POST /v1/meals`` body — `extra="forbid"`로 silent unknown field 차단.

    Story 2.1: ``raw_text`` 빈 문자열·whitespace-only 거부 (1차 게이트, trim 정규화 —
    모바일 ``zod.trim()``과 wire 단일화 / P1). ``ate_at`` 미지정 시 DB-side ``now()``
    fallback (server_default). 미래 시점 거부는 도메인 룰 미존재 (catch-up 시나리오
    허용). naive datetime은 거부 (P19 / D3 결정).

    Story 2.2: ``raw_text``를 *Optional*로 변경 — *최소 한 종(`raw_text` 또는
    `image_key`) 필요*. 사진-only 입력 허용. ``image_key`` ownership 검증은 라우터
    inline (Pydantic field_validator는 user context 미접근).
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = Field(default=None, min_length=1, max_length=2000)
    ate_at: datetime | None = None
    image_key: str | None = Field(default=None, max_length=512)

    @field_validator("raw_text")
    @classmethod
    def _validate_not_whitespace(cls, v: str | None) -> str | None:
        """trim 후 길이 재검증 — 공백만 입력된 본문 차단 + 정규화 (P1)."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("raw_text must not be whitespace-only")
        return stripped

    @field_validator("ate_at")
    @classmethod
    def _validate_ate_at_tz(cls, v: datetime | None) -> datetime | None:
        return _reject_naive_ate_at(v)

    @model_validator(mode="after")
    def _at_least_one_input(self) -> MealCreateRequest:
        """`raw_text`/`image_key` 둘 다 None 거부 — 빈 식단 row 차단 (Story 2.2)."""
        if self.raw_text is None and self.image_key is None:
            raise ValueError("at least one of raw_text, image_key required")
        return self


class MealUpdateRequest(BaseModel):
    """``PATCH /v1/meals/{meal_id}`` body — 모든 필드 absent 시 400 (최소 1 필드 필수).

    Story 2.1: ``raw_text=null``과 *필드 부재*는 동일 처리 (no-op, D4 결정). naive
    ``ate_at`` 거부 (P19 / D3 결정). raw_text는 trim 정규화 (P1).

    Story 2.2: ``image_key`` 추가 — *명시 `null` = 클리어 (사진 제거)*, *키 부재 = no-op*.
    Pydantic v2 `model_fields_set`로 absent vs explicit null 구분 (라우터 inline).
    `_at_least_one_field` model_validator는 *값이 아닌 송신 여부* 검사 (D4 explicit
    null 시맨틱 보존 — 단순 `is None` 검사로는 의미 손실).
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = Field(default=None, min_length=1, max_length=2000)
    ate_at: datetime | None = None
    image_key: str | None = Field(default=None, max_length=512)

    @field_validator("raw_text")
    @classmethod
    def _validate_not_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("raw_text must not be whitespace-only")
        return stripped

    @field_validator("ate_at")
    @classmethod
    def _validate_ate_at_tz(cls, v: datetime | None) -> datetime | None:
        return _reject_naive_ate_at(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> MealUpdateRequest:
        # `model_fields_set`로 *송신 여부* 검사 (Story 2.2 갱신).
        # `raw_text=null` (D4 — no-op) 또는 `image_key=null` (클리어) 송신은 *각각의
        # 의미가 있는* 필드 송신 — 단순 `is None` 검사로는 의미 손실. Story 2.1 validator
        # 단순화 케이스(`is None`)를 본 스토리에서 갱신.
        sent_fields = self.model_fields_set.intersection({"raw_text", "ate_at", "image_key"})
        if not sent_fields:
            raise ValueError("at least one of raw_text, ate_at, image_key required")
        return self


class MealResponse(BaseModel):
    """식단 단건 응답 — 9 필드 (Story 2.1 7 + Story 2.2 image_key + image_url).

    ``deleted_at`` / ``image_key`` / ``image_url`` NULL 시에도 키 유지 (스키마 안정성).
    ``image_url``은 derived — `image_key` 있으면 `_resolve_public_url(image_key)`,
    없으면 None (`_meal_to_response` helper에서 계산).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    raw_text: str
    ate_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    image_key: str | None
    image_url: str | None


class MealListResponse(BaseModel):
    """식단 목록 응답. ``next_cursor``는 본 스토리에서 항상 ``null`` (Story 2.4 입력)."""

    meals: list[MealResponse]
    next_cursor: str | None = None


def _meal_to_response(meal: Meal) -> MealResponse:
    """ORM → 응답 모델 변환 단일 지점 (Story 1.5 ``_build_profile_response`` 패턴).

    Story 2.2: ``image_url``은 ``image_key``에서 derive (public CDN URL).
    """
    image_url = r2_adapter._resolve_public_url(meal.image_key) if meal.image_key else None
    return MealResponse(
        id=meal.id,
        user_id=meal.user_id,
        raw_text=meal.raw_text,
        ate_at=meal.ate_at,
        created_at=meal.created_at,
        updated_at=meal.updated_at,
        deleted_at=meal.deleted_at,
        image_key=meal.image_key,
        image_url=image_url,
    )


def _validate_image_key_ownership(image_key: str, user_id: uuid.UUID) -> None:
    """`meals/{user_id}/` prefix 검증 — cross-user image_key 도용 차단.

    Pydantic field_validator는 user context 미접근 → 라우터 inline 호출.
    image_key=None은 검증 대상 X (호출 측에서 None 체크).
    """
    expected_prefix = f"meals/{user_id}/"
    if not image_key.startswith(expected_prefix):
        raise MealImageOwnershipError(
            f"image_key does not belong to current user (expected prefix {expected_prefix!r})"
        )


# --- Endpoints -------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_meal(
    body: MealCreateRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> MealResponse:
    """식단 생성 — INSERT + RETURNING으로 race-free 응답.

    ``ate_at`` 미지정 시 ``func.now()`` fallback (DB-side 단일 시계). 응답 build는
    ``commit`` *이전*에 — expired 객체 lazy-load 회피 (Story 1.5 패턴).

    Story 2.2: ``image_key`` ownership 검증 + 사진-only 입력 시 ``raw_text`` placeholder
    fallback (`PHOTO_ONLY_RAW_TEXT_PLACEHOLDER`). Story 2.3 OCR이 결과로 덮어씀.
    """
    # Story 2.2 — image_key ownership 검증 (Pydantic 통과 후 router-inline).
    if body.image_key is not None:
        _validate_image_key_ownership(body.image_key, user.id)

    # 사진-only 입력 시 raw_text placeholder fallback. body.raw_text가 None이거나
    # (실제 trim된) 빈 문자열일 가능성을 Pydantic이 차단하므로 None 체크만으로 충분.
    effective_raw_text = body.raw_text
    if effective_raw_text is None:
        effective_raw_text = PHOTO_ONLY_RAW_TEXT_PLACEHOLDER

    values: dict[str, object] = {
        "user_id": user.id,
        "raw_text": effective_raw_text,
    }
    # ``ate_at``가 None이면 server_default(``now()``) 사용 — 명시 NULL 전달 회피.
    if body.ate_at is not None:
        values["ate_at"] = body.ate_at
    if body.image_key is not None:
        values["image_key"] = body.image_key

    result = await db.execute(insert(Meal).values(**values).returning(Meal))
    created = result.scalar_one()
    response = _meal_to_response(created)
    await db.commit()
    logger.info(
        "meals.created",
        user_id=str(user.id),
        meal_id=str(created.id),
        raw_text_len=len(effective_raw_text),
        ate_at_iso=created.ate_at.isoformat(),
        has_image=body.image_key is not None,
    )
    return response


@router.get("")
async def list_meals(
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> MealListResponse:
    """자기 식단 목록 조회 — 인증만 (PIPA Art.35).

    ``WHERE user_id = current_user.id AND deleted_at IS NULL`` 강제 — 다른 사용자
    노출 / soft-deleted 노출 회귀 차단. ``ORDER BY ate_at DESC`` (partial index hit).

    날짜 wire 시맨틱(KST/UTC drift)은 Story 2.4 deferred (W50). ``cursor`` 비-null
    송신은 거부 (P18 / D2 결정 — silent 무시 → 무한 루프 footgun 차단). ``next_cursor``
    는 항상 ``null``.
    """
    # P18 — `cursor` 비-null 거부 (D2 결정).
    if cursor is not None:
        raise MealQueryValidationError("cursor pagination not yet supported (Story 2.4)")
    # P15 — `from_date > to_date` 거부 (typo / swap → silent empty list 회피).
    if from_date is not None and to_date is not None and from_date > to_date:
        raise MealQueryValidationError("from_date must not be after to_date")

    stmt = select(Meal).where(Meal.user_id == user.id, Meal.deleted_at.is_(None))
    if from_date is not None:
        stmt = stmt.where(Meal.ate_at >= from_date)
    if to_date is not None:
        # ``ate_at < to_date + 1 day`` (inclusive) — 같은 날짜 입력 시 자기 자신 포함.
        stmt = stmt.where(Meal.ate_at < to_date + timedelta(days=1))
    stmt = stmt.order_by(Meal.ate_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return MealListResponse(
        meals=[_meal_to_response(m) for m in rows],
        next_cursor=None,
    )


@router.patch("/{meal_id}")
async def update_meal(
    meal_id: uuid.UUID,
    body: MealUpdateRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> MealResponse:
    """식단 수정 — 단일 SQL ``update().where(id, user_id, deleted_at IS NULL).returning()``.

    소유권 미일치 / 존재 X / soft-deleted 모두 동일 404 + ``code=meals.not_found``
    (enumeration 차단).

    Story 2.2:
    - ``image_key`` 추가 — *명시 `null` = 클리어*, *키 부재 = no-op* (Pydantic v2
      `model_fields_set`로 absent vs explicit null 구분).
    - ``image_key`` ownership 검증 — None이 아닐 때만 (None=클리어는 검증 대상 X).
    - PATCH 후 *raw_text + image_key 둘 다 None* invariant — `raw_text` DB NOT NULL +
      Story 2.1 D4 시맨틱(`raw_text=null` 송신은 no-op)으로 SQL 레벨 unreachable.
      별도 가드 X (YAGNI, 추가 SELECT round-trip 0).
    """
    # Story 2.2 — image_key ownership 검증 (None=클리어는 검증 대상 X).
    if body.image_key is not None:
        _validate_image_key_ownership(body.image_key, user.id)

    # P5 — `updated_at`는 모델 ``onupdate=text("now()")``가 자동 갱신 → 명시 set 불필요.
    # Story 2.2 — `model_fields_set`로 *송신 여부* 검사 (D4 시맨틱).
    sent = body.model_fields_set
    values: dict[str, object | None] = {}
    changed_fields: list[str] = []
    # raw_text: explicit null은 no-op (Story 2.1 D4 정합).
    if "raw_text" in sent and body.raw_text is not None:
        values["raw_text"] = body.raw_text
        changed_fields.append("raw_text")
    # ate_at: explicit null은 no-op (D4 정합).
    if "ate_at" in sent and body.ate_at is not None:
        values["ate_at"] = body.ate_at
        changed_fields.append("ate_at")
    # image_key: explicit null = 클리어 (D4와 *다른* 시맨틱 — Story 2.2 의도). nullable
    # 컬럼이라 None 명시 송신이 의미 있음. SQLAlchemy `update().values(image_key=None)`은
    # ``image_key = NULL`` SQL 발행.
    if "image_key" in sent:
        values["image_key"] = body.image_key
        changed_fields.append("image_key")

    result = await db.execute(
        update(Meal)
        .where(
            Meal.id == meal_id,
            Meal.user_id == user.id,
            Meal.deleted_at.is_(None),
        )
        .values(**values)
        .returning(Meal)
        .execution_options(populate_existing=True)
    )
    updated = result.scalar_one_or_none()
    if updated is None:
        raise MealNotFoundError("meal not found")
    response = _meal_to_response(updated)
    await db.commit()
    logger.info(
        "meals.updated",
        user_id=str(user.id),
        meal_id=str(meal_id),
        changed_fields=changed_fields,
        has_image=updated.image_key is not None,
    )
    return response


@router.delete("/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal(
    meal_id: uuid.UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
) -> Response:
    """식단 soft delete — ``UPDATE meals SET deleted_at = now() WHERE ... RETURNING id``.

    물리 삭제 X (soft delete만). 30일 grace + 물리 파기는 Story 5.2 책임. 이미
    soft-deleted된 meal은 404 (멱등 *조회* 결과 일관성 + enumeration 차단).
    """
    # P5 — `updated_at`는 모델 ``onupdate=text("now()")``가 자동 갱신.
    result = await db.execute(
        update(Meal)
        .where(
            Meal.id == meal_id,
            Meal.user_id == user.id,
            Meal.deleted_at.is_(None),
        )
        .values(deleted_at=func.now())
        .returning(Meal.id)
    )
    deleted_id = result.scalar_one_or_none()
    if deleted_id is None:
        raise MealNotFoundError("meal not found")
    await db.commit()
    logger.info(
        "meals.deleted",
        user_id=str(user.id),
        meal_id=str(meal_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
