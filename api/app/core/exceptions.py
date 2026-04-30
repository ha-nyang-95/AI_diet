"""RFC 7807 Problem Details + 도메인 예외 계층 (Story 1.2 / 1.3 / 1.4).

전체 횡단 표준:
- 모든 에러 응답 media_type = `application/problem+json`.
- `code` 필드는 카탈로그화 — Story 1.2 `auth.*`, Story 1.3 `consent.basic.*` /
  `consent.version_mismatch`, Story 1.4 `consent.automated_decision.*` 3건.
- 401 응답에 `WWW-Authenticate: Bearer ...` 헤더 추가는 main.py 핸들러가 담당.
- 409 version mismatch 예외(``ConsentVersionMismatchError`` /
  ``AutomatedDecisionConsentVersionMismatchError``)는 ``latest_versions``
  instance attribute 보유 → main.py 핸들러가 ``X-Consent-Latest-Version`` 헤더
  첨부(Story 1.4 W13 흡수). 헤더 인코딩은 ``encode_latest_version_header``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict

PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json"
DEFAULT_PROBLEM_TYPE: Final[str] = "about:blank"

# Story 1.4 — 409 version mismatch 응답에 첨부되는 헤더 이름. 클라이언트는 본 헤더를
# *옵션 hint*로 사용 — body의 ``code``/``detail``이 1차 신호. RFC 9110 §5.6.1
# list-based 헤더 패턴(다중 entry는 ``; ``로 구분). 본 스토리는 첫 mismatch entry만
# 인코딩(UX 노이즈 회피 + 클라이언트 단순성).
X_CONSENT_LATEST_VERSION_HEADER: Final[str] = "X-Consent-Latest-Version"


def encode_latest_version_header(latest_versions: dict[str, str]) -> str:
    """`<doc_type>=<version>` 단일/다중 entry 인코딩.

    다중 entry는 정렬 후 ``; ``로 구분(결정성 + RFC 9110 §5.6.1.2 list-based
    헤더 안전 패턴 정합). 빈 dict는 빈 문자열 — 호출 측이 이 상황을 회피해야 한다.
    """
    return "; ".join(f"{k}={v}" for k, v in sorted(latest_versions.items()))


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details + `code` 확장 필드."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = DEFAULT_PROBLEM_TYPE
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str  # 우리 확장 — auth.*, validation.*, http.*

    def to_response_dict(self) -> dict[str, Any]:
        return self.model_dump()


class BalanceNoteError(Exception):
    """프로젝트 도메인 예외 base.

    각 서브클래스가 status / code / title을 ClassVar로 선언한다. `to_problem`이
    이 ClassVar들을 읽어 ProblemDetail을 생성한다.
    """

    status: ClassVar[int] = 500
    code: ClassVar[str] = "internal.error"
    title: ClassVar[str] = "Internal Server Error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail

    def to_problem(self, *, instance: str | None = None) -> ProblemDetail:
        return ProblemDetail(
            title=self.title,
            status=self.status,
            detail=self.detail or self.title,
            instance=instance,
            code=self.code,
        )


# --- Auth 계층 ---


class AuthError(BalanceNoteError):
    status: ClassVar[int] = 401
    code: ClassVar[str] = "auth.error"
    title: ClassVar[str] = "Authentication Error"


class InvalidIdTokenError(AuthError):
    code: ClassVar[str] = "auth.google.id_token_invalid"
    title: ClassVar[str] = "Google ID token invalid"


class EmailUnverifiedError(AuthError):
    code: ClassVar[str] = "auth.google.email_unverified"
    title: ClassVar[str] = "Google email not verified"


class AccessTokenExpiredError(AuthError):
    code: ClassVar[str] = "auth.access_token.expired"
    title: ClassVar[str] = "Access token expired"


class AccessTokenInvalidError(AuthError):
    code: ClassVar[str] = "auth.access_token.invalid"
    title: ClassVar[str] = "Access token invalid"


class RefreshTokenInvalidError(AuthError):
    code: ClassVar[str] = "auth.refresh.invalid"
    title: ClassVar[str] = "Refresh token invalid"


class RefreshTokenReplayError(AuthError):
    code: ClassVar[str] = "auth.refresh.replay_detected"
    title: ClassVar[str] = "Refresh token replay detected"


class IssuerMismatchError(AuthError):
    code: ClassVar[str] = "auth.token.issuer_mismatch"
    title: ClassVar[str] = "Token issuer mismatch"


class AdminRoleRequiredError(AuthError):
    status: ClassVar[int] = 403
    code: ClassVar[str] = "auth.admin.role_required"
    title: ClassVar[str] = "Admin role required"


class AccountDeletedError(AuthError):
    status: ClassVar[int] = 403
    code: ClassVar[str] = "auth.account.deleted"
    title: ClassVar[str] = "Account deleted"


# --- Consent 계층 (Story 1.3) ---


class ConsentError(BalanceNoteError):
    status: ClassVar[int] = 403
    code: ClassVar[str] = "consent.error"
    title: ClassVar[str] = "Consent Error"


class BasicConsentMissingError(ConsentError):
    status: ClassVar[int] = 403
    code: ClassVar[str] = "consent.basic.missing"
    title: ClassVar[str] = "Basic consents required"


class ConsentVersionMismatchError(ConsentError):
    # 409 Conflict — RFC 9110 §15.5.10 stale state. Pydantic ValidationError 422와
    # status 충돌 회피.
    status: ClassVar[int] = 409
    code: ClassVar[str] = "consent.version_mismatch"
    title: ClassVar[str] = "Consent version mismatch"

    def __init__(
        self,
        detail: str | None = None,
        *,
        latest_versions: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        # Story 1.4 W13 — main.py 핸들러가 ``X-Consent-Latest-Version`` 헤더를
        # 첨부할 때 참조. 빈 dict면 헤더 첨부 생략.
        self.latest_versions: dict[str, str] = latest_versions or {}


# --- Automated Decision Consent 계층 (Story 1.4) ---


class AutomatedDecisionConsentMissingError(ConsentError):
    """PIPA 2026.03.15 자동화 의사결정 동의 미부여 — 분석 라우터 차단(LLM 비용 0 보호)."""

    status: ClassVar[int] = 403
    code: ClassVar[str] = "consent.automated_decision.missing"
    title: ClassVar[str] = "Automated decision consent required"


class AutomatedDecisionConsentNotGrantedError(ConsentError):
    """``DELETE /automated-decision`` 호출 시 동의 row가 없거나 미동의 상태."""

    status: ClassVar[int] = 404
    code: ClassVar[str] = "consent.automated_decision.not_granted"
    title: ClassVar[str] = "Automated decision consent not granted"


class AutomatedDecisionConsentVersionMismatchError(ConsentError):
    """클라이언트가 보낸 ``automated_decision_version``이 SOT와 불일치."""

    status: ClassVar[int] = 409
    code: ClassVar[str] = "consent.automated_decision.version_mismatch"
    title: ClassVar[str] = "Automated decision consent version mismatch"

    def __init__(
        self,
        detail: str | None = None,
        *,
        latest_versions: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.latest_versions: dict[str, str] = latest_versions or {}


# --- Meal 계층 (Story 2.1) ---


class MealError(BalanceNoteError):
    """Epic 2 식단 도메인 예외 base. Story 2.2 R2 업로드 실패 / Story 2.3 OCR 장애 /
    Story 2.5 큐잉 실패 등 후속 스토리가 본 base 하위 코드 카탈로그 확장."""

    status: ClassVar[int] = 500
    code: ClassVar[str] = "meals.error"
    title: ClassVar[str] = "Meal Error"


class MealNotFoundError(MealError):
    """소유권 미일치 / 존재 X / soft-deleted 모두 동일 응답 (404 일원화 — enumeration
    차단). PATCH/DELETE에서 `update().where(id, user_id, deleted_at IS NULL)` 결과
    None일 때 raise."""

    status: ClassVar[int] = 404
    code: ClassVar[str] = "meals.not_found"
    title: ClassVar[str] = "Meal not found"


class MealQueryValidationError(MealError):
    """`/v1/meals` GET 쿼리 파라미터 validation 실패 — `from_date > to_date` (P15)
    또는 `cursor` 비-null 송신(P18, Story 2.4 입력)."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "meals.query.invalid"
    title: ClassVar[str] = "Meal query validation error"


# --- Meal Image 계층 (Story 2.2 — R2 presigned URL + 사진 입력 흐름) ---


class MealImageError(MealError):
    """식단 사진 도메인 예외 base (R2 presigned URL / 업로드 검증 / cross-user 도용 등).

    `MealError` 하위 — `meals.image.*` 코드 카탈로그. *Abstract base* — 직접
    instantiate 금지(모든 서브클래스가 status/code/title을 명시 override).
    direct-raise 방어로 default `status=400`을 유지(이전 500 default가 leak 시
    server-error 위장하던 가능성 차단).
    """

    status: ClassVar[int] = 400
    code: ClassVar[str] = "meals.image.error"
    title: ClassVar[str] = "Meal Image Error"


class R2UploadValidationError(MealImageError):
    """R2 presigned URL 발급 시 입력 검증 실패 — content_type whitelist 위반 또는
    content_length 초과 (서버 측 1차 게이트). Pydantic Literal/Field가 router 진입
    전 차단하므로 본 예외는 *adapter-level defensive double-gate* (settings/runtime
    분기) — 클라이언트가 router 우회로 adapter 직접 호출하는 시나리오 보호."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "meals.image.upload_invalid"
    title: ClassVar[str] = "Image upload validation failed"


class R2NotConfiguredError(MealImageError):
    """R2 환경변수 4종(`r2_account_id`, `r2_access_key_id`, `r2_secret_access_key`,
    `r2_bucket`) 미설정 시 503 fail-fast — dev/CI 부팅 통과 + 첫 호출 시 차단.

    `r2_public_base_url`은 *optional 5번째 envvar* — 미설정 시
    `<account_id>.r2.dev/<bucket>` fallback 사용(adapter._resolve_public_url). 즉
    R2 *클라이언트 생성*에 필수는 4종이며, 5번째는 *표시 URL prefix override*만 담당.
    prod에서는 부팅 시 settings 검증으로 조기 차단해야 하나 현재 baseline은 runtime
    fail-fast(Story 8 hardening 시 부팅 검증 추가)."""

    status: ClassVar[int] = 503
    code: ClassVar[str] = "meals.image.r2_unconfigured"
    title: ClassVar[str] = "Image upload service unavailable"


class MealImageOwnershipError(MealImageError):
    """`image_key`가 `meals/{current_user.id}/` prefix와 미일치 — cross-user
    image_key 도용 차단 (사용자 A가 사용자 B의 image_key를 자기 식단에 첨부하는
    attack 차단). 라우터 inline 검증 (Pydantic field_validator는 user context
    미접근)."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "meals.image.foreign_key_rejected"
    title: ClassVar[str] = "Image key does not belong to current user"


class MealImageNotUploadedError(MealImageError):
    """`image_key`가 R2에 실제로 PUT 되지 않은 상태 — `head_object` HEAD-check 실패
    (P21 / D1 결정). 클라이언트가 presign 발급 후 PUT 단계 실패/생략한 경우 또는
    악의적 attach 시도(orphan 키 사용) 차단. R2 storage abuse + 깨진 image_url 방어."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "meals.image.not_uploaded"
    title: ClassVar[str] = "Image key not uploaded to R2"


# --- Meal Image OCR 계층 (Story 2.3 — OpenAI Vision 추출 + 사용자 확인 카드) ---


class MealOCRUnavailableError(MealImageError):
    """OCR Vision API 일시 장애 — tenacity retry 후 최종 실패(`openai.APIError` /
    `openai.RateLimitError` / `httpx.TimeoutException` / `httpx.HTTPError` /
    `OPENAI_API_KEY` 미설정). 모바일은 graceful degradation Alert로 *"사진 인식
    일시 장애 — 텍스트로 다시 입력해주세요"* 분기 (NFR-I3 정합)."""

    status: ClassVar[int] = 503
    code: ClassVar[str] = "meals.image.ocr_unavailable"
    title: ClassVar[str] = "Image OCR service unavailable"


class MealOCRImageUrlMissingError(MealImageError):
    """`r2_adapter.resolve_public_url(image_key)`가 None — R2 public URL 미설정.
    `R2NotConfiguredError`(boto3 client 생성)와 *분리* — 본 예외는 *public URL 노출*
    경로. 모바일 동일 alert, 운영 로그·Sentry에서는 분리(원인 파악 용이)."""

    status: ClassVar[int] = 503
    code: ClassVar[str] = "meals.image.ocr_image_url_missing"
    title: ClassVar[str] = "Image public URL not configured (R2)"


class MealOCRPayloadInvalidError(MealImageError):
    """Vision이 structured output 위반(JSON Schema 검증 실패 / Pydantic
    ValidationError). OpenAI SDK `parse` API는 schema 강제하나 *방어로* — 502 Bad
    Gateway는 RFC 9110 정합(*upstream invalid response*)."""

    status: ClassVar[int] = 502
    code: ClassVar[str] = "meals.image.ocr_payload_invalid"
    title: ClassVar[str] = "Image OCR returned invalid payload"
