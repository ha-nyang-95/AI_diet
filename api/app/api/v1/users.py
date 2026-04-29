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

import contextlib
import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, update

from app.api.deps import DbSession, current_user, require_basic_consents
from app.db.models.user import User
from app.domain.allergens import normalize_allergens
from app.domain.health_profile import ActivityLevel, HealthGoal

logger = structlog.get_logger(__name__)

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
    # ``allow_inf_nan=False`` — NaN/Infinity wire format을 명시 거부 → DB Numeric(5,1)
    # DataError(500) 회피하고 RFC 7807 400 + ``code=validation.error`` 정상 분기.
    weight_kg: float = Field(ge=1.0, le=500.0, allow_inf_nan=False)
    height_cm: int = Field(ge=50, le=300)
    activity_level: ActivityLevel
    health_goal: HealthGoal
    # ``max_length=22`` — 도메인 상한과 일치, 1M-element duplicate DoS 차단.
    allergies: list[str] = Field(default_factory=list, max_length=22)

    @field_validator("weight_kg")
    @classmethod
    def _validate_weight_precision(cls, v: float) -> float:
        """소수 첫째 자리까지만 허용 — DB ``Numeric(5,1)``의 silent rounding 차단.

        70.55 같은 값이 백엔드에서 70.6으로 무성 반올림 후 응답되면 사용자가 입력한
        값과 응답이 불일치 (Story 5.1 prefill UX). 1자리 초과 정밀도는 명시 거부.
        """
        if round(v, 1) != v:
            raise ValueError("weight_kg must have at most 1 decimal place")
        return v

    @field_validator("allergies")
    @classmethod
    def _validate_allergens(cls, v: list[str]) -> list[str]:
        """22종 부분집합 검증 + dedup + NFC 정규화 + 정의 순 정렬.

        invalid 항목 → ``ValueError("unknown allergen: '<value>'; ...")`` raise.
        Pydantic이 ValidationError로 wrap → ``main.py:validation_exception_handler``가
        RFC 7807 400 + ``errors`` 배열에 ``msg`` 필드로 메시지 forward (top-level
        ``detail``은 정적 "Request validation failed" — 글로벌 핸들러 회귀 차단).
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
    - ``allergies`` ``None → []`` 빈 배열 fallback (``is not None`` 명시 분기 — DB의 *NULL*과
      *empty list*를 같은 ``[]`` 응답으로 통합. profile 입력 여부는 ``profile_completed_at``
      으로 판별).
    """
    return HealthProfileResponse(
        age=user.age,
        weight_kg=float(user.weight_kg) if user.weight_kg is not None else None,
        height_cm=user.height_cm,
        activity_level=user.activity_level,
        health_goal=user.health_goal,
        allergies=list(user.allergies) if user.allergies is not None else [],
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

    ``UPDATE ... RETURNING``으로 race-free 응답 — commit 후 별도 SELECT 시
    동시 다른 device POST가 끼어들면 응답이 *방금 보낸 값*이 아닌 *마지막 commit
    값*이 되는 race를 차단. ``profile_completed_at`` / ``updated_at`` 양쪽 모두
    DB-side ``func.now()`` 단일 시계 — Python ``datetime.now()`` 와의 clock skew 회피.

    응답 build는 ``commit`` *이전*에 수행 — AsyncSession은 ``commit`` 후 모든 객체를
    expire 시키므로, expired 객체 속성 접근이 lazy-load를 trigger해
    ``sqlalchemy.exc.MissingGreenlet`` (async context lazy-load 금지) 가능.
    RETURNING으로 메모리에 이미 로드된 데이터를 commit 전에 직렬화 후 commit.

    Story 1.6 — ``onboarded_at = func.coalesce(User.onboarded_at, func.now())``로 단일
    UPDATE 안에서 *기존 NULL이면 now() set, 이미 set이면 그대로* (멱등). Story 5.1
    프로필 수정 시점에도 ``onboarded_at``은 변경되지 않아 *최초 온보딩 시점*이 보존됨.
    ``onboarded_first_time`` 로깅은 update 직전 ORM 객체 값으로 판별(NFR-S5: user_id만
    raw, 다른 민감정보 X).
    """
    onboarded_first_time = user.onboarded_at is None
    result = await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            age=body.age,
            weight_kg=body.weight_kg,
            height_cm=body.height_cm,
            activity_level=body.activity_level,
            health_goal=body.health_goal,
            allergies=body.allergies,
            profile_completed_at=func.now(),
            onboarded_at=func.coalesce(User.onboarded_at, func.now()),
            updated_at=func.now(),
        )
        .returning(User)
        .execution_options(populate_existing=True)
    )
    updated_user = result.scalar_one()
    response = _build_profile_response(updated_user)
    await db.commit()
    # 로깅은 commit 성공 후 best-effort — structlog processor 실패가 응답을 500으로
    # 전환하지 않도록 가드(클라이언트는 이미 DB write가 성공한 것을 응답으로 봐야 함.
    # retry 시 COALESCE는 멱등이라 데이터 중복 위험 X이나 사용자 경험 혼선만).
    with contextlib.suppress(Exception):
        logger.info(
            "users.profile.updated",
            user_id=str(user.id),
            onboarded_first_time=onboarded_first_time,
        )
    return response


@router.get("/me/profile")
async def get_health_profile(
    user: Annotated[User, Depends(current_user)],
) -> HealthProfileResponse:
    """프로필 조회 — 인증만(자기 정보 조회는 동의 무관, deps.py 주석 정합).

    미입력 사용자(``profile_completed_at IS NULL``) → 200 + 6 필드 NULL +
    ``allergies=[]`` + ``profile_completed_at=null``. 404 미사용.
    """
    return _build_profile_response(user)
