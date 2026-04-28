"""RFC 7807 Problem Details + 도메인 예외 계층 (Story 1.2).

전체 횡단 표준:
- 모든 에러 응답 media_type = `application/problem+json`.
- `code` 필드는 카탈로그화 — 본 스토리에서 `auth.*` 8건 정의.
- 401 응답에 `WWW-Authenticate: Bearer ...` 헤더 추가는 main.py 핸들러가 담당.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict

PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json"
DEFAULT_PROBLEM_TYPE: Final[str] = "about:blank"


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
