"""Cloudflare R2 어댑터 — Story 2.2 (식단 사진 입력 + presigned URL 발급).

R2는 S3-compat — boto3 S3 client에 endpoint_url 주입 + region "auto" + sigv4 강제.
write는 백엔드 발급 presigned URL(5분 만료), read는 public CDN URL 직접
(architecture line 868 — *인증 토큰 불필요 public read*).

`image_key` 형식: `meals/{user_id}/{uuid4}.{ext}` — user-scoped prefix로 (a)
cross-user enumeration 차단, (b) Story 5.2 R2 GC를 user_id 단위 prefix delete로
단순화, (c) `MealCreateRequest.image_key` ownership 검증을 startswith 1줄로 충족.

본 모듈은 raw boto3 client 생성을 *모듈 lazy singleton*으로 격리 — 매 호출 새
client 생성 시 50ms 오버헤드. settings 환경변수 미설정 시 ``R2NotConfiguredError``
raise (dev/CI 부팅 통과 + runtime fail-fast).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import structlog
from botocore.client import Config

from app.core.config import settings
from app.core.exceptions import R2NotConfiguredError, R2UploadValidationError

# boto3 S3 client는 동적 타입 — `mypy_boto3_s3` stubs 별도 설치 회피(yagni). 본 모듈
# 내부에서만 사용 + 호출 결과는 명시 dataclass로 캡슐화 → 타입 안전성 손실 0.

logger = structlog.get_logger(__name__)

# 5분 만료 — UX 정합(촬영 → 즉시 업로드) + 서명 토큰 유효 시간 최소화. 클라이언트는
# 5분 내 PUT 미완료 시 재발급 호출.
PRESIGNED_URL_EXPIRES_SECONDS: Final[int] = 300
# 10 MB — 모바일 단일 사진 충분(jpeg quality 0.8 + iPhone 12MP 기준 ~3 MB).
# R2 측 enforcement 부재(Content-Length-Range policy 미지원) → 서버 측 1차 게이트.
MAX_UPLOAD_BYTES: Final[int] = 10 * 1024 * 1024

# AC2 명시 5종 mime type — iPhone HEIC/HEIF 포함(모바일 변환 부담 회피).
SupportedContentType = Literal[
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
]
_CONTENT_TYPE_TO_EXT: Final[dict[str, str]] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}

# 모듈 lazy singleton — boto3 client는 thread-safe + 매 호출 새 instance는 ~50ms 오버헤드.
# 타입은 boto3 동적이라 Any 사용 — `mypy_boto3_s3` stubs는 yagni.
_client: Any = None


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """`create_presigned_upload` 반환 — 라우터가 그대로 응답 body로 직렬화.

    - ``upload_url``: 클라이언트가 R2에 PUT할 short-lived 서명 URL (5분 만료).
      *NFR-S5 마스킹 대상* — 로그/Sentry/LangSmith에 raw 출력 X.
    - ``image_key``: R2 object key (`meals/{user_id}/{uuid}.{ext}`). 비-민감 —
      사용자 본인 컨텍스트, 로그 OK.
    - ``public_url``: 표시용 public CDN URL — `r2_public_base_url` 또는
      `r2.dev` fallback. 인증 토큰 무관, 영구 유효 (signed read URL 도입은 Story 8).
    - ``expires_at``: ``upload_url`` 만료 시각 (UTC, 5분 후).
    - ``content_type``: 클라이언트가 PUT 시 ``Content-Type`` 헤더로 실어야 함
      (R2가 sigv4 검증 — 헤더 누락 시 PUT reject).
    """

    upload_url: str
    image_key: str
    public_url: str
    expires_at: datetime
    content_type: str


def _get_client() -> Any:
    """boto3 S3 client lazy singleton — settings 환경변수 미설정 시 503 fail-fast.

    R2 sigv4 강제 — `signature_version="s3v4"` 누락 시 R2가 *Unauthorized* 반환.
    region_name="auto"는 R2 표준(엣지에서 자동 라우팅).
    """
    global _client
    if _client is not None:
        return _client

    # AC2 명시 4종(account_id, access_key_id, secret_access_key, bucket) 검증.
    # public_url은 optional — fallback이 있어 None이어도 OK.
    if not settings.r2_account_id:
        raise R2NotConfiguredError("R2 not configured: r2_account_id missing")
    if not settings.r2_access_key_id:
        raise R2NotConfiguredError("R2 not configured: r2_access_key_id missing")
    if not settings.r2_secret_access_key:
        raise R2NotConfiguredError("R2 not configured: r2_secret_access_key missing")
    if not settings.r2_bucket:
        raise R2NotConfiguredError("R2 not configured: r2_bucket missing")

    import boto3  # late import — boto3 import는 ~150 ms, dev/CI 부팅 fast-path 보호.

    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return _client


def _reset_client_for_tests() -> None:
    """테스트 hook — settings env 변경 후 _client singleton 무효화.

    pytest monkeypatch 후 다음 호출이 새 settings를 반영하도록.
    """
    global _client
    _client = None


def _content_type_to_ext(content_type: str) -> str:
    """5종 whitelist 위반 시 ``R2UploadValidationError(400)``."""
    ext = _CONTENT_TYPE_TO_EXT.get(content_type)
    if ext is None:
        raise R2UploadValidationError(
            f"unsupported content_type: {content_type} "
            f"(expected one of {sorted(_CONTENT_TYPE_TO_EXT)})"
        )
    return ext


def _generate_image_key(user_id: uuid.UUID, ext: str) -> str:
    """`meals/{user_id}/{uuid4}.{ext}` — user-scoped prefix + unguessable UUID."""
    return f"meals/{user_id}/{uuid.uuid4()}.{ext}"


def _resolve_public_url(image_key: str) -> str:
    """`r2_public_base_url` 우선, 미설정 시 `*.r2.dev` fallback.

    Cloudflare custom domain 또는 `<account_id>.r2.dev/<bucket>` 표준. dev/CI에서
    `r2_public_base_url`은 비어 있을 수 있으나 `r2_account_id` + `r2_bucket`은 R2
    클라이언트 생성에서 이미 검증됨.
    """
    base = settings.r2_public_base_url.rstrip("/")
    if base:
        return f"{base}/{image_key}"
    return f"https://{settings.r2_account_id}.r2.dev/{settings.r2_bucket}/{image_key}"


def create_presigned_upload(
    user_id: uuid.UUID,
    content_type: str,
    content_length: int,
) -> PresignedUpload:
    """5분 만료 PUT presigned URL + 표시용 public URL 한 쌍 발급.

    검증 순서: (1) content_type whitelist (`R2UploadValidationError` if fail),
    (2) content_length 1~10 MB (`R2UploadValidationError` if fail),
    (3) settings 환경변수 검증 (`R2NotConfiguredError` if fail) — `_get_client()` 내부.

    sigv4 서명 계산은 *pure CPU* — 실제 R2 도달 X. 단위 테스트 안전 (boto3 client는
    settings 주입만으로 동작, monkeypatch로 env override 가능).
    """
    if content_length < 1:
        raise R2UploadValidationError(f"content_length must be >= 1 byte (got {content_length})")
    if content_length > MAX_UPLOAD_BYTES:
        raise R2UploadValidationError(
            f"content_length must be <= {MAX_UPLOAD_BYTES} bytes (got {content_length})"
        )
    ext = _content_type_to_ext(content_type)

    client = _get_client()
    image_key = _generate_image_key(user_id, ext)
    upload_url: str = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket,
            "Key": image_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRES_SECONDS,
    )
    public_url = _resolve_public_url(image_key)
    expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_EXPIRES_SECONDS)

    # NFR-S5 — `upload_url` raw 출력 X (서명 토큰 노출 차단). image_key/content_type/length만.
    logger.info(
        "r2.presigned_url.created",
        user_id=str(user_id),
        image_key=image_key,
        content_type=content_type,
        content_length=content_length,
        expires_in_seconds=PRESIGNED_URL_EXPIRES_SECONDS,
    )
    return PresignedUpload(
        upload_url=upload_url,
        image_key=image_key,
        public_url=public_url,
        expires_at=expires_at,
        content_type=content_type,
    )
