"""Storage 어댑터 — Story 2.2 (R2) + Story 8.5 (Supabase Storage 분기 swap).

모듈 이름은 *historical* — ``api/app/adapters/r2.py`` 그대로 유지하되 내부 분기.
``STORAGE_PROVIDER=r2`` (default, 외주 인수 옵션 보존) | ``STORAGE_PROVIDER=supabase``
(Render+Supabase prod 미니멀 패턴). 외부 시그니처(``create_presigned_upload`` /
``head_object_exists`` / ``resolve_public_url`` / ``PresignedUpload``)는 **동일** —
호출처(``meals_images.py``, ``data_export_service.py`` 등) 변경 0.

R2 분기(boto3):
  S3-compat — boto3 S3 client에 endpoint_url 주입 + region "auto" + sigv4 강제.
  write는 백엔드 발급 presigned URL(5분 만료), read는 public CDN URL 직접.

Supabase 분기(storage3):
  Supabase Storage `create_signed_upload_url`(5분 만료 PUT URL) + `create_signed_url`
  (1h 만료 download URL — Vision OCR가 5분 이상 여유 + bucket private 정합) +
  `list`(HEAD-equivalent — prefix 검색).

``image_key`` 형식: ``meals/{user_id}/{uuid4}.{ext}`` — user-scoped prefix로 (a)
cross-user enumeration 차단, (b) Story 5.2 R2 GC를 user_id 단위 prefix delete로
단순화, (c) ``MealCreateRequest.image_key`` ownership 검증을 1줄로 충족(P2 — UUID
형식 + ext whitelist + path traversal 차단을 Pydantic regex로 통합).

본 모듈은 raw boto3/storage3 client 생성을 *모듈 lazy singleton*으로 격리. settings
환경변수 미설정 시 ``StorageNotConfiguredError`` 부모/child raise — dev/CI 부팅 통과
+ runtime fail-fast.

P1 — ``_client`` 보호: ``threading.Lock`` double-checked locking. sync boto3/storage3
호출은 라우터에서 ``asyncio.to_thread``로 격리(event loop 보호).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import boto3
import structlog
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.exceptions import (
    R2NotConfiguredError,
    R2UploadValidationError,
    SupabaseStorageNotConfiguredError,
)

logger = structlog.get_logger(__name__)

# 5분 만료 — UX 정합(촬영 → 즉시 업로드) + 서명 토큰 유효 시간 최소화. 클라이언트는
# 5분 내 PUT 미완료 시 재발급 호출.
PRESIGNED_URL_EXPIRES_SECONDS: Final[int] = 300
# Supabase signed download URL TTL (1h) — Vision OCR `image_url` forward에 5분 이상 여유.
# bucket private 유지(NFR-S5 정합) + signed URL 만료 후 외부 재접근 차단.
SIGNED_DOWNLOAD_URL_EXPIRES_SECONDS: Final[int] = 3600
# 10 MB — 모바일 단일 사진 충분(jpeg quality 0.8 + iPhone 12MP 기준 ~3 MB).
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

# 모듈 lazy singleton — 매 호출 새 instance는 ~50ms 오버헤드.
# Provider별 별 변수 — 동시 양 분기 활성 케이스(테스트 등) 충돌 회피.
_r2_client: Any = None
_supabase_storage: Any = None
_client_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """``create_presigned_upload`` 반환 — 라우터가 그대로 응답 body로 직렬화.

    - ``upload_url``: 클라이언트가 R2/Supabase에 PUT할 short-lived 서명 URL (5분 만료).
      *NFR-S5 마스킹 대상* — 로그/Sentry/LangSmith에 raw 출력 X.
    - ``image_key``: object key (`meals/{user_id}/{uuid}.{ext}`). 비-민감 — 사용자 본인
      컨텍스트, 로그 OK.
    - ``public_url``: 표시용 URL — R2 분기는 public CDN URL(인증 토큰 무관, 영구 유효),
      Supabase 분기는 1h signed download URL.
    - ``expires_at``: ``upload_url`` 만료 시각 (UTC, 5분 후).
    - ``content_type``: 클라이언트가 PUT 시 ``Content-Type`` 헤더로 실어야 함.
    """

    upload_url: str
    image_key: str
    public_url: str
    expires_at: datetime
    content_type: str


# =============================================================================
# Provider 분기 헬퍼
# =============================================================================


def _get_r2_client() -> Any:
    """boto3 S3 client lazy singleton — settings 환경변수 미설정 시 503 fail-fast."""
    global _r2_client
    if _r2_client is not None:
        return _r2_client

    with _client_lock:
        if _r2_client is not None:
            return _r2_client

        if not settings.r2_account_id:
            raise R2NotConfiguredError("R2 not configured: r2_account_id missing")
        if not settings.r2_access_key_id:
            raise R2NotConfiguredError("R2 not configured: r2_access_key_id missing")
        if not settings.r2_secret_access_key:
            raise R2NotConfiguredError("R2 not configured: r2_secret_access_key missing")
        if not settings.r2_bucket:
            raise R2NotConfiguredError("R2 not configured: r2_bucket missing")

        _r2_client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        return _r2_client


def _get_supabase_storage() -> Any:
    """storage3 sync client lazy singleton — settings 환경변수 미설정 시 503 fail-fast.

    storage3는 supabase-py 메타패키지의 storage 서브패키지지만 *직접 dependency*로
    사용(realtime/postgrest/auth 등 미사용 sibling 제외 — Render 이미지 size 정합).
    """
    global _supabase_storage
    if _supabase_storage is not None:
        return _supabase_storage

    with _client_lock:
        if _supabase_storage is not None:
            return _supabase_storage

        if not settings.supabase_url:
            raise SupabaseStorageNotConfiguredError("Supabase not configured: supabase_url missing")
        if not settings.supabase_service_key:
            raise SupabaseStorageNotConfiguredError(
                "Supabase not configured: supabase_service_key missing"
            )
        if not settings.supabase_storage_bucket:
            raise SupabaseStorageNotConfiguredError(
                "Supabase not configured: supabase_storage_bucket missing"
            )

        # storage3 sync client. headers 패턴은 supabase 공식 — service_role 키로
        # `Authorization: Bearer` + `apikey` 동시 set(서버측 정합).
        from storage3 import create_client as _create_client  # noqa: PLC0415

        storage_url = f"{settings.supabase_url.rstrip('/')}/storage/v1"
        _supabase_storage = _create_client(
            storage_url,
            headers={
                "apiKey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            is_async=False,
        )
        return _supabase_storage


def _reset_client_for_tests() -> None:
    """테스트 hook — settings env 변경 후 client singleton 무효화.

    pytest monkeypatch 후 다음 호출이 새 settings를 반영하도록 R2/Supabase 양쪽 리셋.
    """
    global _r2_client, _supabase_storage
    _r2_client = None
    _supabase_storage = None


# =============================================================================
# 공용 헬퍼
# =============================================================================


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


def _validate_upload_size(content_length: int) -> None:
    """1 byte ~ 10 MB 외 거부."""
    if content_length < 1:
        raise R2UploadValidationError(f"content_length must be >= 1 byte (got {content_length})")
    if content_length > MAX_UPLOAD_BYTES:
        raise R2UploadValidationError(
            f"content_length must be <= {MAX_UPLOAD_BYTES} bytes (got {content_length})"
        )


# =============================================================================
# Public API — provider 분기는 내부에서 처리, 호출처는 단일 시그니처만 인지
# =============================================================================


def resolve_public_url(image_key: str) -> str | None:
    """표시용 URL — provider별 분기.

    R2 분기: `r2_public_base_url` 우선, 미설정 시 `*.r2.dev` fallback. R2 미설정 시 None.
    Supabase 분기: 1h signed download URL(bucket private + Vision OCR 5분 이상 여유).
    """
    provider = settings.storage_provider
    if provider == "supabase":
        try:
            client = _get_supabase_storage()
        except SupabaseStorageNotConfiguredError:
            # P3 — 미설정 환경 graceful (`None` 반환 — meals_images 호출 측이 503 변환).
            return None
        try:
            signed = client.from_(settings.supabase_storage_bucket).create_signed_url(
                image_key,
                SIGNED_DOWNLOAD_URL_EXPIRES_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "storage.supabase.signed_url_failed",
                image_key=image_key,
                error=str(exc),
            )
            return None
        # storage3 API: response dict — key는 SDK 버전에 따라 `signedURL` 또는 `signedUrl`.
        url: str | None = (
            signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")
        )
        return url

    # R2 분기 (default)
    base = settings.r2_public_base_url.rstrip("/")
    if base:
        return f"{base}/{image_key}"
    if settings.r2_account_id and settings.r2_bucket:
        return f"https://{settings.r2_account_id}.r2.dev/{settings.r2_bucket}/{image_key}"
    return None


def head_object_exists(image_key: str) -> bool:
    """object가 실제로 존재하는지 HEAD-check (P21 — D1 결정) — provider별 분기.

    R2 분기: ``head_object`` (boto3) — 404/403/NoSuchKey 모두 미존재로 일원화.
    Supabase 분기: ``list(path=prefix, options={search=filename})`` — 0건이면 미존재.

    미설정 시 ``R2NotConfiguredError`` / ``SupabaseStorageNotConfiguredError`` 전파.
    """
    provider = settings.storage_provider
    if provider == "supabase":
        client = _get_supabase_storage()
        # `meals/{user_id}/{uuid}.{ext}` → prefix=`meals/{user_id}`, filename=`{uuid}.{ext}`
        if "/" in image_key:
            prefix, filename = image_key.rsplit("/", 1)
        else:
            prefix, filename = "", image_key
        try:
            files = client.from_(settings.supabase_storage_bucket).list(
                path=prefix,
                options={"limit": 1, "search": filename},
            )
        except Exception:
            # 네트워크/SDK 에러는 전파(R2 분기와 동일 정합 — 5xx로 globalhandler 변환).
            raise
        if not isinstance(files, list):
            return False
        # storage3 응답: [{"name": "<filename>", ...}, ...]. search 결과 정확 매칭만 인정.
        return any(f.get("name") == filename for f in files if isinstance(f, dict))

    # R2 분기 (default)
    client = _get_r2_client()
    try:
        client.head_object(Bucket=settings.r2_bucket, Key=image_key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchKey", "Not Found", "403", "Forbidden"}:
            return False
        raise
    return True


def create_presigned_upload(
    user_id: uuid.UUID,
    content_type: str,
    content_length: int,
) -> PresignedUpload:
    """5분 만료 PUT presigned URL + 표시용 URL 한 쌍 발급 — provider별 분기.

    검증 순서: (1) content_type whitelist (`R2UploadValidationError` if fail),
    (2) content_length 1~10 MB (`R2UploadValidationError` if fail),
    (3) settings 환경변수 검증 (`R2NotConfiguredError` / ``SupabaseStorageNotConfiguredError``
    if fail) — `_get_*_client()` 내부.

    R2 분기: ``boto3.generate_presigned_url('put_object', ...)``. ContentType 헤더 sigv4
    검증 — 클라이언트가 PUT 시 명시 필수.
    Supabase 분기: ``create_signed_upload_url(path)`` — Supabase 자체 token URL. 클라이언트
    PUT은 URL 자체에 token 포함, 별 헤더 불필요.
    """
    _validate_upload_size(content_length)
    ext = _content_type_to_ext(content_type)
    image_key = _generate_image_key(user_id, ext)

    provider = settings.storage_provider
    if provider == "supabase":
        client = _get_supabase_storage()
        signed = client.from_(settings.supabase_storage_bucket).create_signed_upload_url(image_key)
        upload_url = (
            signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url") or ""
        )
        # Supabase signed_url은 *상대 경로*일 수 있음 — 절대 URL로 정규화.
        if upload_url and not upload_url.startswith(("http://", "https://")):
            upload_url = f"{settings.supabase_url.rstrip('/')}{upload_url}"
        public_url = resolve_public_url(image_key) or ""
        expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_EXPIRES_SECONDS)
        logger.info(
            "storage.supabase.signed_upload_created",
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

    # R2 분기 (default)
    client = _get_r2_client()
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket,
            "Key": image_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRES_SECONDS,
    )
    public_url = resolve_public_url(image_key) or ""
    expires_at = datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_EXPIRES_SECONDS)
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
