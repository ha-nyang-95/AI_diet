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
