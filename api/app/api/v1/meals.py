"""``/v1/meals`` — 식단 텍스트·사진·OCR 입력 + CRUD (Story 2.1 + 2.2 + 2.3 + 2.5).

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
- ``raw_text`` *내용*은 로그에 raw 출력 X — ``raw_text_len``만 forward (NFR-S5).

Story 2.5 추가 (W46 흡수):
- ``POST /v1/meals``에 ``Idempotency-Key`` 헤더 처리 — UUID v4 형식 검증 + race-free
  SELECT-INSERT-CATCH-SELECT 패턴 (RFC 9110 200 idempotent replay). 같은 키 재송신
  시 기존 row 200 응답, 첫 INSERT는 그대로 201.
- soft-deleted row와 같은 키 재사용 시도는 ``MealIdempotencyKeyConflictDeletedError(409)``
  분기 — 사용자가 새 키로 재시도하도록 안내.
- PATCH/DELETE는 헤더 무시 — *POST 흐름만* idempotency 처리. PATCH/DELETE에 헤더
  송신돼도 분기 X (회귀 0건).

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

Story 2.3 추가:
- ``parsed_items`` (Vision OCR 결과 jsonb) 필드 추가 — `MealCreateRequest`/
  `MealUpdateRequest`/`MealResponse` 모두 nullable. `ParsedMealItem` Pydantic
  모델 재사용(`app.adapters.openai_adapter`). max_length 20.
- ``parsed_items 단독 + image_key 부재 거부`` — *parsed_items는 image_key의 부속*
  (Vision 호출 결과 영속화), image_key 없이 의미 없음.
- ``_format_parsed_items_to_raw_text`` 서버 fallback — POST `raw_text=None and
  parsed_items is not None` 시 적용. *클라이언트 표준 변환*과 동일 — DF2(`(사진
  입력)` placeholder collision) 자연 해소.
- PATCH는 `parsed_items=null` 명시 송신 시 *클리어*, 키 부재 시 *no-op*
  (image_key 시맨틱 정합).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Final, Literal
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import r2 as r2_adapter
from app.adapters.openai_adapter import ParsedMealItem
from app.api.deps import DbSession, current_user, require_basic_consents
from app.core.exceptions import (
    BalanceNoteError,
    MealIdempotencyKeyConflictDeletedError,
    MealIdempotencyKeyInvalidError,
    MealImageNotUploadedError,
    MealImageOwnershipError,
    MealNotFoundError,
    MealParsedItemsRequiresImageKeyError,
    MealQueryValidationError,
)
from app.db.models.meal import Meal
from app.db.models.user import User

# Story 2.4 — `GET /v1/meals` 날짜 필터 KST 강제 (W50 해소, D1 결정 — option B). KST
# 자정 boundary는 Python `datetime.combine(date, time.min, tzinfo=_KST)`로 명시 변환,
# Postgres `AT TIME ZONE` 회피 (asyncpg driver 호환성 + Python 단일 책임). 다중 TZ
# 지원은 Growth NFR-L4.
_KST: Final[ZoneInfo] = ZoneInfo("Asia/Seoul")

# P2 — `image_key`는 `meals/<user_uuid>/<image_uuid>.<ext>` 형식으로 고정. 5종 ext
# whitelist + UUID v4 형식 검증 + path traversal/duplicate slash/empty 차단을 단일
# regex로 통합. user_id 일치는 라우터 inline (regex로 표현 불가).
_IMAGE_KEY_PATTERN: Final[str] = (
    r"^meals/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"\.(?:jpg|png|webp|heic|heif)$"
)
# UUID(36) + UUID(36) + ext(≤4) + slashes(7) + "meals"(5) ≈ 90. 128로 충분 + 여유.
_IMAGE_KEY_MAX_LENGTH: Final[int] = 128

# 사진-only 입력 (parse 미호출) 시 ``raw_text`` 자동 fallback. Story 2.3에서 parse
# 흐름 통과 시 ``_format_parsed_items_to_raw_text``가 우선 적용되어 placeholder 진입
# 차단(DF2 자연 해소). 본 placeholder는 *parsed_items 없는 사진-only 입력 only*.
# i18n은 OUT (NFR-L2 한국어 1차).
PHOTO_ONLY_RAW_TEXT_PLACEHOLDER = "(사진 입력)"

# Story 2.3 — POST `parsed_items` 최대 항목 수 (Pydantic Field max_length).
# AbuseGuard: 영업 데모 한정 합리적 상한 + Story 8 tunable.
_PARSED_ITEMS_MAX_LENGTH: Final[int] = 20

# Story 2.5 — `Idempotency-Key` 헤더는 UUID v4 형식 강제. Python `uuid.UUID(version=4)`
# 회피(version arg가 무시되는 케이스 존재) — application-level regex 명시 (Story 2.2
# `_IMAGE_KEY_PATTERN` 패턴 정합). 길이 36자 hard cap 동시 강제 (over-length DoS 차단).
_IDEMPOTENCY_KEY_PATTERN: Final[str] = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_IDEMPOTENCY_KEY_REGEX: Final[re.Pattern[str]] = re.compile(_IDEMPOTENCY_KEY_PATTERN)
_IDEMPOTENCY_KEY_LENGTH: Final[int] = 36

# CR P3 — partial UNIQUE 위반 catch를 인덱스 이름으로 한정 (FK/CHECK 위반 등 비-멱등
# IntegrityError를 잘못된 replay path로 진입시키지 않기 위함). DB-side index 이름은
# 마이그레이션 0009와 동기 — 인덱스 rename 시 이 상수도 갱신 필요.
_IDEMPOTENCY_INDEX_NAME: Final[str] = "idx_meals_user_id_idempotency_key_unique"


def _validate_idempotency_key(key: str | None) -> str | None:
    """``Idempotency-Key`` 헤더 형식 검증 + 정규화 (Story 2.5, CR P12).

    None / 빈 문자열 / 공백 패딩은 *"미송신과 동등"*으로 처리(``None`` 반환 — 기존
    baseline 정합 + 정상 흐름). 비공백 패딩 후 형식 위반만 즉시
    ``MealIdempotencyKeyInvalidError(400)`` raise. UUID v4 regex + 길이 36 강제.
    """
    if key is None:
        return None
    stripped = key.strip()
    if not stripped:
        return None
    if len(stripped) != _IDEMPOTENCY_KEY_LENGTH or not _IDEMPOTENCY_KEY_REGEX.match(stripped):
        raise MealIdempotencyKeyInvalidError("Idempotency-Key must be a valid UUID v4 (RFC 4122)")
    return stripped


def _format_parsed_items_to_raw_text(items: list[ParsedMealItem]) -> str:
    """``parsed_items`` → 한국어 한 줄 raw_text 변환 (서버 fallback).

    예: ``[{"name":"짜장면","quantity":"1인분"}, {"name":"군만두","quantity":"4개"}]``
    → ``"짜장면 1인분, 군만두 4개"``.

    빈 quantity는 양 표시 생략 (``"바나나"`` 처럼). 빈 items는 빈 문자열 — POST
    라우터에서 None 분기로 처리 (호출 측 invariant).

    클라이언트 ``formatParsedItemsToRawText``(mobile/features/meals/parsedItemsFormat.ts)와
    *동일 변환* — 클라이언트가 raw_text를 안 보낸 케이스에서도 일관 동작 보장.
    """
    parts = [(f"{item.name} {item.quantity}".rstrip()) for item in items]
    return ", ".join(parts)


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
    image_key: str | None = Field(
        default=None,
        max_length=_IMAGE_KEY_MAX_LENGTH,
        pattern=_IMAGE_KEY_PATTERN,
    )
    parsed_items: list[ParsedMealItem] | None = Field(
        default=None,
        max_length=_PARSED_ITEMS_MAX_LENGTH,
    )

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
        """`raw_text`/`image_key` 둘 다 None 거부 — 빈 식단 row 차단 (Story 2.2).

        Story 2.3 — `parsed_items` 단독 + image_key 부재 거부. parsed_items는
        Vision 호출 결과 영속화이므로 image_key 없이 의미 없음.
        """
        if self.raw_text is None and self.image_key is None:
            raise ValueError("at least one of raw_text, image_key required")
        if self.parsed_items is not None and self.image_key is None:
            raise ValueError("parsed_items requires image_key")
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
    image_key: str | None = Field(
        default=None,
        max_length=_IMAGE_KEY_MAX_LENGTH,
        pattern=_IMAGE_KEY_PATTERN,
    )
    parsed_items: list[ParsedMealItem] | None = Field(
        default=None,
        max_length=_PARSED_ITEMS_MAX_LENGTH,
    )

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
        # Story 2.2 갱신: *실제 update가 발생하는* 필드가 하나라도 있는지 확인.
        # - `image_key`는 `null` 송신이 *clear* 의미 — 송신 여부만 확인.
        # - `raw_text`/`ate_at`는 `null` 송신이 *no-op*(D4 정합) — 라우터가 무시해
        #   `update().values()` dict가 빈 채로 SQLAlchemy에 도달하는 footgun 차단.
        # Gemini Code Assist PR #12 medium 코멘트(discussion 3161733852) 수용.
        # Story 2.3 갱신: `parsed_items`는 `null` 송신이 *clear* 의미 (image_key
        # 시맨틱 정합) — 송신 여부만 확인.
        sent = self.model_fields_set
        has_effective_change = (
            "image_key" in sent
            or "parsed_items" in sent
            or ("raw_text" in sent and self.raw_text is not None)
            or ("ate_at" in sent and self.ate_at is not None)
        )
        if not has_effective_change:
            raise ValueError(
                "at least one effective field required "
                "(raw_text/ate_at must be non-null, "
                "or image_key/parsed_items must be provided)"
            )
        return self


class MealMacros(BaseModel):
    """식단 매크로 영양 정보 — 식약처 OpenAPI 표준 키 정합 (architecture line 289).

    Story 2.4 — Epic 3 forward-compat. 모든 필드 ``ge=0`` non-negative 단언. 본 스토리
    baseline은 *항상 None*(서버 join X) — 실제 채움은 Story 3.3 (`meal_analyses` 테이블
    + LangGraph 노드 + ``app/domain/fit_score.py`` 알고리즘) / Story 3.5 (fit_score 룰).
    """

    model_config = ConfigDict(extra="forbid")

    carbohydrate_g: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    energy_kcal: float = Field(ge=0)


class MealAnalysisSummary(BaseModel):
    """식단 AI 분석 요약 — Epic 3 ``meal_analyses`` 테이블 1:1 매핑 forward-compat 슬롯.

    Story 2.4 — Pydantic 인터페이스만 정의. 본 스토리 baseline은 ``MealResponse.analysis_summary``
    *항상 None*(서버 join X) — 실제 채움은 Story 3.3 / 3.5. 별도 endpoint 분리는
    yagni — list 응답에 슬롯 통합(Story 3.x perf hardening 시점에 분리 검토).

    fields:

    - ``fit_score``: 0-100 (FR21 정합).
    - ``fit_score_label``: 5단계 텍스트 라벨 — NFR-A4 색약 대응. ``allergen_violation``
      (FR22 알레르기 0점 단락) / ``low`` / ``moderate`` / ``good`` / ``excellent``.
    - ``macros``: 식약처 OpenAPI 표준 키.
    - ``feedback_summary``: 1줄 피드백 (max 120) — FR23 인용형 풀 텍스트는 ``[meal_id].tsx``
      채팅(Story 3.7 SSE).
    """

    model_config = ConfigDict(extra="forbid")

    fit_score: int = Field(ge=0, le=100)
    fit_score_label: Literal["allergen_violation", "low", "moderate", "good", "excellent"]
    macros: MealMacros
    feedback_summary: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _validate_score_label_consistency(self) -> MealAnalysisSummary:
        # CR P3 — fit_score와 fit_score_label 정합성 검증. 클라이언트 카드 색상은 label,
        # 숫자는 score 기준이라 NFR-A4 색약 대응(녹색 95에 *"부족"* 표시 등) 의도가
        # 깨지지 않도록 cross-field invariant 강제. allergen_violation은 FR22 0점 단락.
        if self.fit_score_label == "allergen_violation":
            if self.fit_score != 0:
                raise ValueError(
                    "fit_score_label='allergen_violation' requires fit_score == 0 (FR22)"
                )
            return self
        bands: dict[str, tuple[int, int]] = {
            "low": (0, 39),
            "moderate": (40, 59),
            "good": (60, 79),
            "excellent": (80, 100),
        }
        lo, hi = bands[self.fit_score_label]
        if not (lo <= self.fit_score <= hi):
            raise ValueError(
                f"fit_score={self.fit_score} does not match label='{self.fit_score_label}'"
                f" (band {lo}-{hi})"
            )
        return self


class MealResponse(BaseModel):
    """식단 단건 응답 — 11 필드 (Story 2.1+2.2+2.3 10 + Story 2.4 analysis_summary).

    ``deleted_at`` / ``image_key`` / ``image_url`` / ``parsed_items`` /
    ``analysis_summary`` NULL 시에도 키 유지 (스키마 안정성, architecture line 481).
    ``image_url``은 derived — `image_key` 있으면 `_resolve_public_url(image_key)`,
    없으면 None (`_meal_to_response` helper에서 계산).

    Story 2.4 — ``analysis_summary``는 본 스토리 baseline *항상 None*(서버 join X).
    Story 3.x가 ``meal_analyses`` JOIN으로 채움.
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
    parsed_items: list[ParsedMealItem] | None
    analysis_summary: MealAnalysisSummary | None


class MealListResponse(BaseModel):
    """식단 목록 응답. ``next_cursor``는 본 스토리에서 항상 ``null`` (Story 2.4 입력)."""

    meals: list[MealResponse]
    next_cursor: str | None = None


def _meal_to_response(meal: Meal) -> MealResponse:
    """ORM → 응답 모델 변환 단일 지점 (Story 1.5 ``_build_profile_response`` 패턴).

    Story 2.2: ``image_url``은 ``image_key``에서 derive (public CDN URL).
    P3 — ``r2_adapter.resolve_public_url``은 R2 미설정 시 ``None`` 반환(broken
    `https:///<key>` URL 차단). 호출 측은 None을 그대로 응답 ``image_url``로 forward.

    Story 2.3: ``parsed_items``는 jsonb → ``list[ParsedMealItem]`` 자동 역직렬화
    (Pydantic ``model_validate``). NULL은 ``None`` 그대로 forward. CR P2 fix
    (2026-04-30): per-item validate를 try/except로 격리 — 단일 손상 row가 GET 전체
    500 만들지 않도록 corrupt 항목 drop + warn 로그.
    """
    image_url = r2_adapter.resolve_public_url(meal.image_key) if meal.image_key else None
    parsed_items: list[ParsedMealItem] | None
    if meal.parsed_items is None:
        parsed_items = None
    else:
        parsed_items = []
        for raw_item in meal.parsed_items:
            try:
                parsed_items.append(ParsedMealItem.model_validate(raw_item))
            except ValidationError as exc:
                logger.warning(
                    "meals.parsed_items.malformed",
                    meal_id=str(meal.id),
                    error=str(exc),
                )
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
        parsed_items=parsed_items,
        # Story 2.4 — Epic 3 forward-compat 슬롯. ``meal_analyses`` JOIN은 Story 3.3 책임.
        analysis_summary=None,
    )


def _validate_image_key_ownership(image_key: str, user_id: uuid.UUID) -> None:
    """`meals/{user_id}/` prefix 검증 — cross-user image_key 도용 차단.

    Pydantic field_validator는 user context 미접근 → 라우터 inline 호출.
    image_key=None은 검증 대상 X (호출 측에서 None 체크).
    P2 — image_key 형식(UUID + ext + 단일 slash)은 Pydantic ``pattern``이 차단하므로
    본 함수는 *user_id 일치*만 책임 (regex 통과 후 호출됨).
    """
    expected_prefix = f"meals/{user_id}/"
    if not image_key.startswith(expected_prefix):
        raise MealImageOwnershipError(
            f"image_key does not belong to current user (expected prefix {expected_prefix!r})"
        )


async def _verify_image_uploaded(image_key: str) -> None:
    """R2에 ``image_key`` 객체가 실제로 PUT 됐는지 HEAD-check (P21 / D1 결정).

    sync boto3 호출은 ``asyncio.to_thread``로 격리(event-loop block 회피, P1 정합).
    R2 미설정 시 ``R2NotConfiguredError`` 전파 — 글로벌 핸들러 503.
    """
    exists = await asyncio.to_thread(r2_adapter.head_object_exists, image_key)
    if not exists:
        raise MealImageNotUploadedError(
            f"image_key not found in R2 (presign 발급 후 PUT 미수행 또는 만료): {image_key}"
        )


# --- Endpoints -------------------------------------------------------------


async def _create_meal_idempotent_or_replay(
    db: AsyncSession,
    values: dict[str, object],
    idempotency_key: str | None,
) -> tuple[Meal, bool]:
    """Race-free SELECT-then-INSERT-then-CATCH-then-SELECT 패턴 (Story 2.5).

    Returns ``(meal, was_replay)`` — ``was_replay=True`` 시 라우터가 200 OK로 응답
    분기 (RFC 9110 idempotent retry).

    흐름:
    1. ``idempotency_key`` None → 기존 단순 INSERT … RETURNING (회귀 0건).
    2. 헤더 송신 → ``select(...).where(user_id, idempotency_key, deleted_at IS NULL)``
       1차 조회 → 있으면 (existing, True) 반환.
    3. 1차 조회 미존재 → ``insert(...).returning(Meal)`` 시도. ``IntegrityError``
       catch 시 ``await db.rollback()`` 후 *전체 row*(deleted_at 포함) 재 SELECT —
       soft-deleted hit이면 ``MealIdempotencyKeyConflictDeletedError(409)`` raise,
       active hit이면 (existing, True) 반환, 둘 다 0건이면 5xx fallback.

    rollback 후 재 SELECT는 ``db.execute``로 신규 transaction 시작 — SQLAlchemy
    AsyncSession은 rollback 후 implicit begin 지원.
    """
    if idempotency_key is None:
        result = await db.execute(insert(Meal).values(**values).returning(Meal))
        return result.scalar_one(), False

    user_id = values["user_id"]
    # 1차 조회 — active row만(soft-deleted 제외).
    existing = (
        await db.execute(
            select(Meal).where(
                Meal.user_id == user_id,
                Meal.idempotency_key == idempotency_key,
                Meal.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    # 2차 시도 — INSERT + RETURNING. UNIQUE 제약 위반(race) 시 catch + 재 SELECT.
    insert_values = {**values, "idempotency_key": idempotency_key}
    try:
        result = await db.execute(insert(Meal).values(**insert_values).returning(Meal))
        return result.scalar_one(), False
    except IntegrityError as exc:
        # CR P3 — partial UNIQUE 제약 위반만 replay path로 진입. FK/CHECK 등 비-멱등
        # IntegrityError는 그대로 raise(라우터/글로벌 핸들러가 처리). 인덱스 이름 매칭은
        # asyncpg/SQLAlchemy 모두 ``str(e.orig)``에 노출 — 이름 변경 시 상수 동기 필수.
        if _IDEMPOTENCY_INDEX_NAME not in str(exc.orig):
            raise
        await db.rollback()
        # 재 SELECT — deleted_at 무관 (soft-deleted row 충돌 분기 위해 필터 X).
        replay = (
            await db.execute(
                select(Meal).where(
                    Meal.user_id == user_id,
                    Meal.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if replay is None:
            # race lost + 재 SELECT 0건 — 비정상 상태(예: 다른 transaction 미커밋).
            # 5xx fallback (BalanceNoteError default 500).
            raise BalanceNoteError(
                "idempotent replay race resolution failed (no row found after IntegrityError)"
            ) from None
        if replay.deleted_at is not None:
            raise MealIdempotencyKeyConflictDeletedError(
                "Idempotency-Key collides with a soft-deleted meal — please use a new key"
            ) from None
        return replay, True


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "description": "Idempotent replay (Story 2.5 — same Idempotency-Key)",
            "model": MealResponse,
        },
        400: {"description": "Validation failed (raw_text / image_key / Idempotency-Key)"},
        409: {"description": "Idempotency-Key collides with soft-deleted meal"},
    },
)
async def create_meal(
    body: MealCreateRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MealResponse:
    """식단 생성 — INSERT + RETURNING으로 race-free 응답.

    ``ate_at`` 미지정 시 ``func.now()`` fallback (DB-side 단일 시계). 응답 build는
    ``commit`` *이전*에 — expired 객체 lazy-load 회피 (Story 1.5 패턴).

    Story 2.2: ``image_key`` ownership 검증 + 사진-only 입력 시 ``raw_text`` placeholder
    fallback (`PHOTO_ONLY_RAW_TEXT_PLACEHOLDER`). Story 2.3 OCR이 결과로 덮어씀.

    Story 2.5 (W46 흡수): ``Idempotency-Key`` 헤더 송신 시 같은 키 재송신은
    ``200 OK`` 응답 (RFC 9110 idempotent retry — resource는 이미 존재). 첫 INSERT는
    그대로 ``201 Created``. ``Idempotency-Key``는 *키 == 한 번* 시맨틱 — 같은 키 +
    다른 ``raw_text``는 첫 응답을 그대로 replay (body diff 무시 — Stripe/Toss 표준 정합).
    """
    # Story 2.5 — Idempotency-Key 형식 검증 + 정규화 (UUID v4 + 길이 36).
    # CR P12 — 빈/공백 헤더는 *"미송신과 동등"*으로 처리(None 반환). 비공백 패딩은 trim 후 검증.
    idempotency_key = _validate_idempotency_key(idempotency_key)

    # Story 2.2 — image_key ownership 검증 (Pydantic 통과 후 router-inline) +
    # P21 R2 head_object HEAD-check (D1 결정 — orphan/미PUT 키 attach 차단).
    if body.image_key is not None:
        _validate_image_key_ownership(body.image_key, user.id)
        await _verify_image_uploaded(body.image_key)

    # 우선순위: (1) 사용자가 raw_text 명시 → 그대로(편집 우선),
    # (2) raw_text 미송신 + parsed_items 송신 → 서버 fallback 변환 (DF2 자연 해소),
    # (3) raw_text 미송신 + parsed_items 미송신 + image_key 송신 → placeholder.
    # Pydantic이 raw_text 빈 문자열 / whitespace-only 차단하므로 None 체크만으로 충분.
    effective_raw_text = body.raw_text
    if effective_raw_text is None and body.parsed_items:
        effective_raw_text = _format_parsed_items_to_raw_text(body.parsed_items)
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
    # Story 2.3 — parsed_items가 None이 아니면 jsonb로 dump (Pydantic → list[dict]).
    if body.parsed_items is not None:
        values["parsed_items"] = [item.model_dump() for item in body.parsed_items]

    # Story 2.5 — race-free SELECT-then-INSERT-then-CATCH-then-SELECT (W46 흡수).
    meal, was_replay = await _create_meal_idempotent_or_replay(db, values, idempotency_key)
    response_body = _meal_to_response(meal)
    await db.commit()

    if was_replay:
        # RFC 9110 — idempotent retry returns 200 (resource already exists).
        response.status_code = status.HTTP_200_OK
        logger.info(
            "meals.create.idempotent_replay",
            user_id=str(user.id),
            meal_id=str(meal.id),
        )
    else:
        logger.info(
            "meals.created",
            user_id=str(user.id),
            meal_id=str(meal.id),
            raw_text_len=len(effective_raw_text),
            ate_at_iso=meal.ate_at.isoformat(),
            has_image=body.image_key is not None,
            has_parsed_items=body.parsed_items is not None,
            parsed_items_count=len(body.parsed_items) if body.parsed_items else 0,
            has_idempotency_key=idempotency_key is not None,
        )
    return response_body


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
    노출 / soft-deleted 노출 회귀 차단.

    Story 2.4 — 날짜 필터는 ``Asia/Seoul`` TZ 자정 boundary로 해석합니다 (W50 해소,
    D1 결정). ``from_date=2026-04-30`` → ``2026-04-30T00:00:00+09:00`` 이상,
    ``to_date=2026-04-30`` → ``2026-05-01T00:00:00+09:00`` 미만. KST 0-9시 식단 누락
    차단(``ate_at='2026-04-30T03:00:00+09:00'`` UTC ``2026-04-29T18:00:00Z``이
    ``from_date=2026-04-30``에 포함). 다중 TZ 지원은 Growth NFR-L4.

    Story 2.4 — ORDER BY 분기 (D2 결정). 날짜 필터 활성 시 ``ate_at ASC``(시간순 —
    아침→저녁, epic AC line 558), 미적용 시 ``ate_at DESC``(최근 식단 우선, Story 8
    cursor pagination forward-compat). partial index ``idx_meals_user_id_ate_at_active``
    는 양방향 hit.

    ``cursor`` 비-null 송신은 거부 (P18 / D2 결정 — silent 무시 → 무한 루프 footgun
    차단). ``next_cursor``는 항상 ``null``. ``analysis_summary``는 항상 ``null``
    (Story 3.x ``meal_analyses`` JOIN 책임 — Story 2.4 baseline은 forward-compat 슬롯만).
    """
    # P18 — `cursor` 비-null 거부 (D2 결정).
    if cursor is not None:
        raise MealQueryValidationError("cursor pagination not yet supported (Story 2.4)")
    # P15 — `from_date > to_date` 거부 (typo / swap → silent empty list 회피).
    if from_date is not None and to_date is not None and from_date > to_date:
        raise MealQueryValidationError("from_date must not be after to_date")
    # P22 — `to_date == date.max` (9999-12-31) 거부. `to_date + timedelta(days=1)` 산술
    # OverflowError → 500 회귀 차단. Pydantic `date` Query는 9999-12-31까지 허용.
    if to_date is not None and to_date >= date.max:
        raise MealQueryValidationError("to_date out of range")

    stmt = select(Meal).where(Meal.user_id == user.id, Meal.deleted_at.is_(None))
    # Story 2.4 (W50 해소, D1) — KST 자정 boundary로 명시 변환. asyncpg는 tz-aware
    # datetime을 그대로 timestamptz로 전달, 비교는 UTC로 정규화 (Postgres 표준).
    if from_date is not None:
        from_dt = datetime.combine(from_date, time.min, tzinfo=_KST)
        stmt = stmt.where(Meal.ate_at >= from_dt)
    if to_date is not None:
        # ``to_date`` inclusive — 다음날 KST 자정 미만 (같은 일자 포함).
        to_dt = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=_KST)
        stmt = stmt.where(Meal.ate_at < to_dt)
    # Story 2.4 (D2) — 날짜 필터 활성 시 ASC, 미적용 시 DESC.
    if from_date is not None or to_date is not None:
        stmt = stmt.order_by(Meal.ate_at.asc())
    else:
        stmt = stmt.order_by(Meal.ate_at.desc())
    stmt = stmt.limit(limit)
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
    # Story 2.2 — image_key ownership 검증 + R2 head_object HEAD-check (P21 / D1).
    # None=클리어는 검증 대상 X.
    if body.image_key is not None:
        _validate_image_key_ownership(body.image_key, user.id)
        await _verify_image_uploaded(body.image_key)

    # P5 — `updated_at`는 모델 ``onupdate=text("now()")``가 자동 갱신 → 명시 set 불필요.
    # Story 2.2 — `model_fields_set`로 *송신 여부* 검사 (D4 시맨틱).
    sent = body.model_fields_set
    # CR P5 fix(2026-04-30) — parsed_items invariant. POST의 _at_least_one_input과
    # 대칭으로 PATCH도 parsed_items=non-null이 image_key 없는 meal에 부착되는 것을
    # 차단(orphan parsed_items). 두 분기:
    #   ① body가 image_key=null + parsed_items=non-null (request만으로 invariant 위반)
    #   ② body가 parsed_items=non-null만 송신, stored image_key=NULL (DB 상태 검증 필요)
    if "parsed_items" in sent and body.parsed_items is not None:
        sets_image_key_non_null = "image_key" in sent and body.image_key is not None
        if not sets_image_key_non_null:
            if "image_key" in sent:
                # body.image_key is None confirmed by sets_image_key_non_null=False
                raise MealParsedItemsRequiresImageKeyError(
                    "parsed_items cannot be set when image_key is being cleared"
                )
            stored_row = (
                await db.execute(
                    select(Meal.image_key, Meal.id).where(
                        Meal.id == meal_id,
                        Meal.user_id == user.id,
                        Meal.deleted_at.is_(None),
                    )
                )
            ).first()
            # stored_row is None: meal not found — let UPDATE handle MealNotFoundError naturally
            # (enumeration 차단 정합).
            if stored_row is not None and stored_row.image_key is None:
                raise MealParsedItemsRequiresImageKeyError(
                    "parsed_items requires meal.image_key (orphan parsed_items rejected)"
                )
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
    # Story 2.3 — parsed_items: explicit null = 클리어 (image_key 시맨틱 정합).
    if "parsed_items" in sent:
        values["parsed_items"] = (
            [item.model_dump() for item in body.parsed_items]
            if body.parsed_items is not None
            else None
        )
        changed_fields.append("parsed_items")

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
        has_parsed_items=updated.parsed_items is not None,
        parsed_items_count=(len(updated.parsed_items) if updated.parsed_items is not None else 0),
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
