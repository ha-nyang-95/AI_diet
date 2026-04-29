"""``/v1/meals/images`` — 식단 사진 입력 R2 presigned URL 발급 (Story 2.2).

1 endpoint:
- ``POST /v1/meals/images/presign`` — content_type + content_length 검증 후 5분
  만료 PUT presigned URL + 표시용 public URL 한 쌍 발급. R2 직접 업로드 흐름의
  진입점 (백엔드는 sig만 발급, 실제 PUT은 클라이언트가 R2에 직접 — Railway
  egress 비용 + 메모리 폭발 회피, architecture line 868).

분리 채택 사유 (vs ``meals.py`` 내 endpoint 추가):
- ``meals.py``(Story 2.1, ~310 라인) 단일 파일 size 한계.
- *image-* prefix 도메인은 forward Story 2.3 OCR endpoint
  (`POST /v1/meals/images/{image_key}/parse`) 흡수 prep — 분리가 forward-compat.
- 1파일 1 router 패턴(architecture line 544) 정합 — `meals_images`는 `meals.py`
  라우터의 *서브 라우터*가 아닌 별도 모듈 + 같은 prefix 등록.

NFR-S5 마스킹 — `upload_url` raw 출력 X (서명 토큰 노출 차단), `image_key`만 forward.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.adapters import r2 as r2_adapter
from app.api.deps import require_basic_consents
from app.db.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter()


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


# --- Endpoints -----------------------------------------------------------------


@router.post("/presign", status_code=status.HTTP_200_OK)
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
    """
    presigned = r2_adapter.create_presigned_upload(
        user_id=user.id,
        content_type=body.content_type,
        content_length=body.content_length,
    )
    logger.info(
        "meals.image.presign_issued",
        user_id=str(user.id),
        image_key=presigned.image_key,
        content_type=presigned.content_type,
        content_length=body.content_length,
        expires_in_seconds=r2_adapter.PRESIGNED_URL_EXPIRES_SECONDS,
    )
    # ISO 8601 UTC 직렬화 — 프론트는 `Date.parse()`로 변환.
    return MealImagePresignResponse(
        upload_url=presigned.upload_url,
        image_key=presigned.image_key,
        public_url=presigned.public_url,
        expires_at=presigned.expires_at.isoformat().replace("+00:00", "Z"),
        content_type=presigned.content_type,
    )
