"""``/v1/meals/images`` — 식단 사진 입력 R2 presigned URL + OCR Vision 파싱.

2 endpoint:
- ``POST /v1/meals/images/presign`` (Story 2.2) — content_type + content_length
  검증 후 5분 만료 PUT presigned URL + 표시용 public URL 한 쌍 발급.
- ``POST /v1/meals/images/parse``   (Story 2.3) — image_key 기반 GPT-4o Vision
  OCR 호출 + ``parsed_items`` (name/quantity/confidence) 응답 + ``low_confidence``
  플래그 (모바일 forced confirmation UX 분기).

분리 채택 사유 (vs ``meals.py`` 내 endpoint 추가):
- ``meals.py``(Story 2.1, ~310 라인) 단일 파일 size 한계.
- *image-* prefix 도메인은 forward Story 2.3 OCR endpoint
  (`POST /v1/meals/images/parse`) 흡수 prep — 분리가 forward-compat.
- 1파일 1 router 패턴(architecture line 544) 정합 — `meals_images`는 `meals.py`
  라우터의 *서브 라우터*가 아닌 별도 모듈 + 같은 prefix 등록.

NFR-S5 마스킹 — `upload_url` raw 출력 X (서명 토큰 노출 차단), `image_key`만 forward.
parse endpoint 로깅도 ``parsed_items`` 내용 raw 출력 X (잠재 식습관 추론) —
items_count + low_confidence + latency_ms만.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC
from typing import Annotated, Final, Literal

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.adapters import openai_adapter
from app.adapters import r2 as r2_adapter
from app.adapters.openai_adapter import VISION_MODEL, ParsedMealItem
from app.api.deps import require_basic_consents
from app.api.v1.meals import (
    _IMAGE_KEY_MAX_LENGTH,
    _IMAGE_KEY_PATTERN,
    _validate_image_key_ownership,
    _verify_image_uploaded,
)
from app.core.exceptions import MealOCRImageUrlMissingError
from app.db.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter()

# Story 2.3 — items가 비었거나 min(confidence) < 0.6일 때 모바일 forced confirmation
# UI 분기 트리거. 임계값은 epic AC 명시(line 544).
LOW_CONFIDENCE_THRESHOLD: Final[float] = 0.6


# --- Pydantic 스키마 -----------------------------------------------------------


class MealImagePresignRequest(BaseModel):
    """``POST /v1/meals/images/presign`` body.

    `content_type`은 Literal로 1차 게이트 — Pydantic이 router 진입 전 차단(400 +
    `code=validation.error`). adapter는 *defensive double-gate* (signature 호출
    경로 보호).

    `content_length`는 Field `ge=1, le=10*1024*1024` — 0 byte 또는 음수, 10 MB
    초과 거부.
    """

    model_config = ConfigDict(extra="forbid")

    content_type: Literal[
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    ]
    content_length: int = Field(ge=1, le=10 * 1024 * 1024)


class MealImagePresignResponse(BaseModel):
    """5 필드 — 라우터가 ``r2_adapter.PresignedUpload`` dataclass에서 직렬화."""

    upload_url: str
    image_key: str
    public_url: str
    expires_at: str
    content_type: str


class MealImageParseRequest(BaseModel):
    """``POST /v1/meals/images/parse`` body — image_key만 (forward-compat: 향후
    `model` / `language_hint` 등 옵션 추가 시 body schema 확장).

    `image_key` regex는 Story 2.2 `meals.py:_IMAGE_KEY_PATTERN` 재사용 — wire 단일화.
    """

    model_config = ConfigDict(extra="forbid")

    image_key: str = Field(
        min_length=1,
        max_length=_IMAGE_KEY_MAX_LENGTH,
        pattern=_IMAGE_KEY_PATTERN,
    )


class MealImageParseResponse(BaseModel):
    """5 필드 — Vision OCR 결과 + 계산된 low_confidence 플래그 + 운영 지표.

    `low_confidence`는 모바일 forced confirmation UI 분기 입력 (items 빈 배열 또는
    min(confidence) < 0.6). `model`은 운영 가시성(향후 `gpt-4o-mini` 다운그레이드
    검토 시 필드 비교).
    """

    image_key: str
    parsed_items: list[ParsedMealItem]
    low_confidence: bool
    model: str
    latency_ms: int


# --- Endpoints -----------------------------------------------------------------


@router.post(
    "/presign",
    status_code=status.HTTP_200_OK,
    responses={
        # P9 — OpenAPI에 도메인 에러 코드 노출(클라이언트 typed handler용).
        # 422는 FastAPI Pydantic ValidationError 자동 등록 — 실제 응답은
        # 글로벌 핸들러가 400 + ``code=validation.error``로 변환.
        400: {"description": "Validation error or unsupported content type"},
        401: {"description": "Authentication required"},
        403: {"description": "Basic consents required"},
        503: {"description": "Image upload service unavailable (R2 unconfigured)"},
    },
)
async def issue_presigned_upload(
    body: MealImagePresignRequest,
    user: Annotated[User, Depends(require_basic_consents)],
) -> MealImagePresignResponse:
    """R2 presigned PUT URL + 표시용 public URL 한 쌍 발급.

    HTTP 200 채택 — presign은 *리소스 생성*이 아닌 *short-lived 토큰 발급*
    (stateless — DB row 0). 201은 부적절. ``Idempotency-Key`` 헤더는 *수신만*
    허용 — 매 호출 새 키 발급(중복 방지 의미 부재 / 같은 key 반복 송신해도 매
    호출 새 image_key 반환).

    에러 흐름:
    - 401 — `auth.access_token.invalid` (`current_user`)
    - 403 — `consent.basic.missing` (`require_basic_consents`)
    - 400 — `validation.error` (Pydantic Literal/Field) 또는
      `meals.image.upload_invalid` (adapter `R2UploadValidationError`)
    - 503 — `meals.image.r2_unconfigured` (`R2NotConfiguredError`)

    P1 — sync boto3 호출(`generate_presigned_url`)은 ``asyncio.to_thread``로
    격리해 event-loop block 회피.
    """
    presigned = await asyncio.to_thread(
        r2_adapter.create_presigned_upload,
        user.id,
        body.content_type,
        body.content_length,
    )
    logger.info(
        "meals.image.presign_issued",
        user_id=str(user.id),
        image_key=presigned.image_key,
        content_type=presigned.content_type,
        content_length=body.content_length,
        expires_in_seconds=r2_adapter.PRESIGNED_URL_EXPIRES_SECONDS,
    )
    # ISO 8601 UTC 직렬화 — `astimezone(UTC)`로 tz 강제 후 `Z`-suffixed strftime
    # (P12 fix — `.replace("+00:00", "Z")`는 microsecond 출력/non-UTC tz 시 fragile).
    expires_at_utc = presigned.expires_at.astimezone(UTC)
    return MealImagePresignResponse(
        upload_url=presigned.upload_url,
        image_key=presigned.image_key,
        public_url=presigned.public_url,
        expires_at=expires_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        content_type=presigned.content_type,
    )


@router.post(
    "/parse",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Validation error or image not uploaded / foreign key"},
        401: {"description": "Authentication required"},
        403: {"description": "Basic consents required"},
        502: {"description": "Image OCR returned invalid payload"},
        503: {"description": "Image OCR or R2 service unavailable"},
    },
)
async def parse_meal_image_endpoint(
    body: MealImageParseRequest,
    user: Annotated[User, Depends(require_basic_consents)],
) -> MealImageParseResponse:
    """식단 사진(R2 업로드 완료) → GPT-4o Vision OCR → ``parsed_items`` 응답.

    HTTP 200 채택 — parse는 *리소스 생성*이 아닌 *idempotent 분석 호출*(stateless —
    DB row 0). 매 호출 새 Vision 호출 + 새 응답(temperature=0.0 강제로 변동성 최소화).
    캐시(`cache:llm:{sha256(image_key)}`)는 Story 8 polish.

    에러 흐름:
    - 401 — `auth.access_token.invalid` (`current_user`)
    - 403 — `consent.basic.missing` (`require_basic_consents`)
    - 400 — `validation.error` (Pydantic regex) /
      `meals.image.foreign_key_rejected` / `meals.image.not_uploaded`
    - 503 — `meals.image.r2_unconfigured` (R2 환경변수) /
      `meals.image.ocr_image_url_missing` (R2 public URL 없음) /
      `meals.image.ocr_unavailable` (Vision API 장애)
    - 502 — `meals.image.ocr_payload_invalid` (Vision schema 위반)

    검증 순서: (1) ownership(prefix), (2) R2 head_object HEAD-check (P21), (3)
    Vision 호출. ownership 실패 시 R2 round-trip 회피 (cost + latency).
    """
    _validate_image_key_ownership(body.image_key, user.id)
    await _verify_image_uploaded(body.image_key)

    image_url = r2_adapter.resolve_public_url(body.image_key)
    if image_url is None:
        # R2 public URL 미설정 — `R2NotConfiguredError`(boto3 client)와 분리된
        # 별도 503 사유. 운영 로그에서 *어디서 막혔는지* 분리 가시성 확보.
        raise MealOCRImageUrlMissingError(
            "R2 public URL unavailable (r2_public_base_url unset and r2.dev fallback unresolved)"
        )

    start = time.monotonic()
    parsed = await openai_adapter.parse_meal_image(image_url, image_key=body.image_key)
    latency_ms = int((time.monotonic() - start) * 1000)

    # low_confidence: items 비었거나 min(confidence) < 0.6 (epic AC 명시).
    low_confidence = (not parsed.items) or any(
        item.confidence < LOW_CONFIDENCE_THRESHOLD for item in parsed.items
    )

    logger.info(
        "meals.image.parse_completed",
        user_id=str(user.id),
        image_key=body.image_key,
        items_count=len(parsed.items),
        low_confidence=low_confidence,
        latency_ms=latency_ms,
    )
    return MealImageParseResponse(
        image_key=body.image_key,
        parsed_items=parsed.items,
        low_confidence=low_confidence,
        model=VISION_MODEL,
        latency_ms=latency_ms,
    )
