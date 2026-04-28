"""`/v1/users/me` — 현재 로그인 사용자 조회 + 건강 프로필 입력/조회.

- ``GET /v1/users/me`` (Story 1.2): 자기 정보 조회. 인증만 — 동의 게이트 X.
  Story 1.5에서 ``profile_completed_at`` 필드 응답 모델 추가(4번째 가드용 분기).
- ``POST /v1/users/me/profile`` (Story 1.5 AC2): 건강 프로필 입력 — 7컬럼 update.
  ``Depends(require_basic_consents)`` 첫 wire (Story 1.3 W14 deferred 흡수).
- ``GET /v1/users/me/profile`` (Story 1.5 AC3): 프로필 값 조회 — 인증만(자기 정보).
  미입력 사용자도 200 + 6 필드 NULL + ``allergies=[]`` 응답(404 X — 사용자는 항상
  존재). prefill 흐름 forward-hook (Story 5.1 수정 흐름).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update

from app.api.deps import DbSession, current_user, require_basic_consents
from app.db.models.user import User
from app.domain.allergens import normalize_allergens
from app.domain.health_profile import ActivityLevel, HealthGoal

router = APIRouter()


# --- Pydantic 스키마 (snake_case 양방향) -----------------------------------


class UserMeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    picture_url: str | None
    role: str
    created_at: datetime
    last_login_at: datetime | None
    onboarded_at: datetime | None
    # Story 1.5 — 4번째 가드 분기에 사용. ``users.profile_completed_at`` 그대로 forward.
    profile_completed_at: datetime | None


class HealthProfileSubmitRequest(BaseModel):
    """``POST /v1/users/me/profile`` body — 6 입력 필드 (profile_completed_at은 backend-managed).

    범위 검증은 Pydantic ``Field(ge=, le=)``로 1차, DB CHECK 제약이 2차(double gate).
    ``allergies`` 22종 검증은 ``field_validator``에서 ``normalize_allergens()`` 호출 —
    invalid 항목 발견 시 ``ValueError`` raise → Pydantic ``ValidationError`` →
    글로벌 핸들러가 RFC 7807 400 + ``code=validation.error``.
    """

    model_config = ConfigDict(extra="forbid")

    age: int = Field(ge=1, le=150)
    weight_kg: float = Field(ge=1.0, le=500.0)
    height_cm: int = Field(ge=50, le=300)
    activity_level: ActivityLevel
    health_goal: HealthGoal
    allergies: list[str] = Field(default_factory=list)

    @field_validator("allergies")
    @classmethod
    def _validate_allergens(cls, v: list[str]) -> list[str]:
        """22종 부분집합 검증 + dedup + 정의 순 정렬.

        invalid 항목 → ``ValueError("unknown allergen: '<value>'; ...")`` raise.
        Pydantic이 ValidationError로 wrap → ``main.py:validation_exception_handler``가
        RFC 7807 400 + ``errors`` 배열에 ``msg`` 필드로 메시지 forward.
        """
        return normalize_allergens(v)


class HealthProfileResponse(BaseModel):
    """``POST/GET /v1/users/me/profile`` 응답 — 7 필드.

    ``allergies``는 NULL → ``[]`` 빈 배열로 응답(클라이언트 분기 단순화).
    ``weight_kg``는 DB ``Decimal`` → JSON wire format ``float`` 직렬화.
    """

    age: int | None
    weight_kg: float | None
    height_cm: int | None
    activity_level: ActivityLevel | None
    health_goal: HealthGoal | None
    allergies: list[str]
    profile_completed_at: datetime | None


def _build_profile_response(user: User) -> HealthProfileResponse:
    """User ORM → HealthProfileResponse 변환.

    - ``weight_kg`` ``Decimal | None → float | None`` 명시 변환 (wire format float 정합).
    - ``allergies`` ``None → []`` 빈 배열 fallback.
    """
    return HealthProfileResponse(
        age=user.age,
        weight_kg=float(user.weight_kg) if user.weight_kg is not None else None,
        height_cm=user.height_cm,
        activity_level=user.activity_level,
        health_goal=user.health_goal,
        allergies=list(user.allergies) if user.allergies else [],
        profile_completed_at=user.profile_completed_at,
    )


# --- Endpoints -------------------------------------------------------------


@router.get("/me")
async def get_me(user: Annotated[User, Depends(current_user)]) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        role=user.role,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        onboarded_at=user.onboarded_at,
        profile_completed_at=user.profile_completed_at,
    )


@router.post("/me/profile")
async def submit_health_profile(
    body: HealthProfileSubmitRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_basic_consents)],  # ← Story 1.3 W14 첫 wire
) -> HealthProfileResponse:
    """프로필 입력 — 7컬럼 update + ``profile_completed_at = now()`` set.

    ``users`` row는 OAuth 시점(Story 1.2)에 이미 존재 — INSERT 분기 X. 항상 200.
    재입력(이미 입력된 사용자가 다시 POST)도 200 + 갱신값 반영 + ``profile_completed_at``
    갱신(*최신 프로필 기록 시점*. 과거 입력 history는 audit_logs Story 7.3 책임).
    """
    now = datetime.now(UTC)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            age=body.age,
            weight_kg=body.weight_kg,
            height_cm=body.height_cm,
            activity_level=body.activity_level,
            health_goal=body.health_goal,
            allergies=body.allergies,
            profile_completed_at=now,
            # ``onupdate=text("now()")`` 이벤트가 sync UPDATE에서 정상 발화하나
            # 명시 set으로 안전망(Story 1.3·1.4 패턴 정합).
            updated_at=func.now(),
        )
    )
    await db.commit()
    refreshed = await db.execute(select(User).where(User.id == user.id))
    return _build_profile_response(refreshed.scalar_one())


@router.get("/me/profile")
async def get_health_profile(
    user: Annotated[User, Depends(current_user)],
) -> HealthProfileResponse:
    """프로필 조회 — 인증만(자기 정보 조회는 동의 무관, deps.py 주석 정합).

    미입력 사용자(``profile_completed_at IS NULL``) → 200 + 6 필드 NULL +
    ``allergies=[]`` + ``profile_completed_at=null``. 404 미사용.
    """
    return _build_profile_response(user)
